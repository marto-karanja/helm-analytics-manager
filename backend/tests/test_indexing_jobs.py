import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from app.core import app_settings
from app.indexing import inspection as inspection_api
from app.indexing import jobs, service
from app.indexing.signals import FetchedPage
from app.models.indexing import AppSetting, PageSignal, SitemapStatus, SitemapUrl, UrlInspection
from app.models.project import Project
from app.db.session import async_session_maker
from tests.fakes import FakeResponse, FakeSession

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

URLSET = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{}</urlset>"""


def sitemap(*paths: str, host="https://site.example") -> bytes:
    return URLSET.format("".join(f"<url><loc>{host}{p}</loc></url>" for p in paths)).encode()


@pytest_asyncio.fixture(autouse=True)
async def isolated():
    """Other modules leave pipeline projects and settings in the shared test database."""
    async with async_session_maker() as db:
        await db.execute(update(Project).values(is_pipeline=False))
        await db.execute(delete(AppSetting))
        for model in (UrlInspection, PageSignal, SitemapUrl, SitemapStatus):
            await db.execute(delete(model))
        await db.commit()


async def make_project(slug_prefix="idx", url="https://site.example/", gsc="https://site.example/") -> Project:
    async with async_session_maker() as db:
        project = Project(
            slug=f"{slug_prefix}-{uuid.uuid4().hex[:8]}", name=slug_prefix, category="seo-content-site",
            url=url, is_pipeline=True, gsc_site_url=gsc,
        )
        db.add(project)
        await db.commit()
        return project


def fetcher(files: dict[str, bytes]):
    return lambda url: files.get(url)


async def urls_of(project, removed=False) -> set[str]:
    async with async_session_maker() as db:
        rows = await db.execute(
            select(SitemapUrl.url).where(
                SitemapUrl.project_id == project.id,
                SitemapUrl.removed_at.is_not(None) if removed else SitemapUrl.removed_at.is_(None),
            )
        )
        return set(rows.scalars())


# ---------------------------------------------------------------- sitemap walk


async def test_sitemap_walk_stores_urls_then_diffs_and_marks_removals():
    project = await make_project()
    files = {"https://site.example/sitemap.xml": sitemap("/a", "/b", "/c")}
    result = await jobs.run_sitemap_walk(async_session_maker, fetch=fetcher(files), now=NOW)
    assert result["status"] == "ok" and result["detail"][project.slug]["urls"] == 3
    assert await urls_of(project) == {f"https://site.example{p}" for p in ("/a", "/b", "/c")}

    files["https://site.example/sitemap.xml"] = sitemap("/b", "/c", "/d")
    result = await jobs.run_sitemap_walk(async_session_maker, fetch=fetcher(files), now=NOW + timedelta(days=1))
    entry = result["detail"][project.slug]
    assert (entry["added"], entry["removed"]) == (1, 1)
    assert await urls_of(project, removed=True) == {"https://site.example/a"}

    files["https://site.example/sitemap.xml"] = sitemap("/a", "/b", "/c", "/d")  # /a comes back
    await jobs.run_sitemap_walk(async_session_maker, fetch=fetcher(files), now=NOW + timedelta(days=2))
    assert await urls_of(project, removed=True) == set()


async def test_failed_walk_never_marks_everything_removed():
    project = await make_project()
    await jobs.run_sitemap_walk(async_session_maker, fetch=fetcher({"https://site.example/sitemap.xml": sitemap("/a")}), now=NOW)
    result = await jobs.run_sitemap_walk(async_session_maker, fetch=fetcher({}), now=NOW + timedelta(days=1))
    assert result["detail"][project.slug]["status"] == "error"
    assert await urls_of(project) == {"https://site.example/a"}


async def test_sitemap_walk_stores_search_console_sitemap_status():
    project = await make_project()
    google = FakeSession()
    list_url = jobs.SITEMAP_LIST_URL.format(site="https%3A%2F%2Fsite.example%2F")
    google.get_responses[list_url] = FakeResponse(
        {
            "sitemap": [
                {
                    "path": "https://site.example/sitemap.xml",
                    "lastSubmitted": "2026-10-03T08:00:00.000Z",
                    "lastDownloaded": "2026-04-12T01:00:00Z",
                    "isPending": True,
                    "errors": "0",
                    "warnings": "2",
                    "contents": [{"type": "web", "submitted": "120", "indexed": "0"}],
                }
            ]
        }
    )
    files = {"https://site.example/sitemap.xml": sitemap("/a")}
    await jobs.run_sitemap_walk(async_session_maker, google_session=google, fetch=fetcher(files), now=NOW)
    async with async_session_maker() as db:
        row = (await db.execute(select(SitemapStatus).where(SitemapStatus.project_id == project.id))).scalar_one()
    assert (row.is_pending, row.warnings, row.submitted_urls) == (True, 2, 120)
    assert row.last_downloaded.year == 2026 and row.last_downloaded.month == 4


async def test_sitemap_status_failure_is_partial_not_fatal():
    project = await make_project()
    google = FakeSession()  # unknown list URL answers {} ... make it 403 instead
    google.get = lambda url, **kw: FakeResponse(status_code=403)
    files = {"https://site.example/sitemap.xml": sitemap("/a")}
    result = await jobs.run_sitemap_walk(async_session_maker, google_session=google, fetch=fetcher(files), now=NOW)
    assert result["detail"][project.slug]["status"] == "partial"
    assert await urls_of(project) == {"https://site.example/a"}


# ---------------------------------------------------------------- page signals

GOOD = "<html><head><title>T {n}</title></head><body><h1>x</h1><p>{words}</p></body></html>"


def page_fetcher(pages: dict[str, FetchedPage]):
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    fetch.calls = calls
    return fetch


async def seed_urls(project, *paths, lastmod=None):
    async with async_session_maker() as db:
        for p in paths:
            db.add(SitemapUrl(project_id=project.id, url=f"https://site.example{p}", lastmod=lastmod, first_seen_at=NOW, last_seen_at=NOW))
        await db.commit()


async def test_page_signals_fetch_new_urls_and_only_changed_ones_afterwards():
    project = await make_project()
    await seed_urls(project, "/a", "/b")
    pages = {
        f"https://site.example{p}": FetchedPage(f"https://site.example{p}", 200, GOOD.format(n=p, words="word " * 400))
        for p in ("/a", "/b")
    }
    fetch = page_fetcher(pages)
    result = await jobs.run_page_signals(async_session_maker, fetch=fetch, now=NOW)
    assert result["detail"][project.slug]["fetched"] == 2

    fetch.calls.clear()
    await jobs.run_page_signals(async_session_maker, fetch=fetch, now=NOW + timedelta(days=1))
    assert fetch.calls == []  # nothing new, nothing changed, nothing stale

    async with async_session_maker() as db:
        await db.execute(update(SitemapUrl).where(SitemapUrl.url == "https://site.example/b").values(lastmod=datetime.now(timezone.utc) + timedelta(days=1)))
        await db.commit()
    await jobs.run_page_signals(async_session_maker, fetch=fetch, now=NOW + timedelta(days=2))
    assert fetch.calls == ["https://site.example/b"]


async def test_page_signals_record_failures_and_use_the_crawler_for_empty_pages(monkeypatch):
    project = await make_project()
    await seed_urls(project, "/ok", "/gone", "/js")
    pages = {
        "https://site.example/ok": FetchedPage("https://site.example/ok", 200, GOOD.format(n="ok", words="word " * 400)),
        "https://site.example/gone": FetchedPage("https://site.example/gone", 404, "<html><body>nope</body></html>"),
        "https://site.example/js": FetchedPage("https://site.example/js", 200, "<html><body><div id=app></div></body></html>"),
    }
    monkeypatch.setattr(jobs, "_crawler_extract", lambda url: GOOD.format(n="js", words="rendered " * 500))
    result = await jobs.run_page_signals(async_session_maker, fetch=page_fetcher(pages), now=NOW)
    assert result["detail"][project.slug]["fetch_failures"] == 1
    async with async_session_maker() as db:
        latest = await service.latest_signals(db, project.id)
    assert latest["https://site.example/gone"].http_status == 404
    assert latest["https://site.example/js"].source == "crawler" and latest["https://site.example/js"].word_count == 501
    assert latest["https://site.example/ok"].source == "http"


async def test_build_signal_records_fetch_errors_and_header_noindex():
    errored = jobs.build_signal(uuid.uuid4(), FetchedPage("https://site.example/x", None, error="Timeout"))
    assert errored.error == "Timeout" and errored.word_count is None
    page = FetchedPage("https://site.example/y", 200, GOOD.format(n="y", words="word " * 400), x_robots_noindex=True)
    assert jobs.build_signal(uuid.uuid4(), page).noindex is True


# ---------------------------------------------------------------- url inspection and budget


def inspect_ok(coverage="Submitted and indexed", verdict="PASS"):
    def respond(url, body):
        return FakeResponse({"inspectionResult": {"indexStatusResult": {"verdict": verdict, "coverageState": coverage, "pageFetchState": "SUCCESSFUL"}}})

    return FakeSession(respond)


async def inspections_count(project=None) -> int:
    async with async_session_maker() as db:
        stmt = select(func.count()).select_from(UrlInspection)
        if project is not None:
            stmt = stmt.where(UrlInspection.project_id == project.id)
        return (await db.execute(stmt)).scalar_one()


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(inspection_api, "MIN_SECONDS_BETWEEN_CALLS", 0)


async def test_inspection_spends_exactly_the_budget_never_inspected_first():
    project = await make_project()
    await seed_urls(project, *[f"/p{i}" for i in range(10)])
    async with async_session_maker() as db:
        await app_settings.put_setting(db, "inspection_budget", 4, "test")
    google = inspect_ok()
    result = await jobs.run_url_inspection(async_session_maker, google, now=NOW)
    assert result["detail"][project.slug]["inspected"] == 4 and len(google.calls) == 4
    assert result["detail"]["_budget"] == {"budget": 4, "spent_before": 0, "chosen": 4}
    assert google.calls[0]["json"]["siteUrl"] == "https://site.example/"

    # a second run the same day has nothing left to spend
    again = await jobs.run_url_inspection(async_session_maker, inspect_ok(), now=NOW + timedelta(hours=1))
    assert again["detail"]["_budget"]["chosen"] == 0
    # the next day it moves on to URLs never inspected, not to re-inspecting
    google2 = inspect_ok()
    await jobs.run_url_inspection(async_session_maker, google2, now=NOW + timedelta(days=1))
    seen = {c["json"]["inspectionUrl"] for c in google2.calls}
    async with async_session_maker() as db:
        first = {r.url for r in (await db.execute(select(UrlInspection).order_by(UrlInspection.inspected_at).limit(4))).scalars()}
    assert len(seen) == 4 and not (seen & first)


async def test_stored_budget_above_the_ceiling_is_clamped_server_side():
    project = await make_project()
    await seed_urls(project, *[f"/p{i}" for i in range(5)])
    async with async_session_maker() as db:
        db.add(AppSetting(key="inspection_budget", value=99999))  # bypasses validation, as a bad migration or DB edit could
        await db.commit()
    result = await jobs.run_url_inspection(async_session_maker, inspect_ok(), now=NOW)
    assert result["detail"]["_budget"]["budget"] == app_settings.INSPECTION_CEILING == 1500


async def test_per_project_split_caps_one_project():
    a, b = await make_project("a", "https://a.example/", "https://a.example/"), await make_project("b", "https://b.example/", "https://b.example/")
    async with async_session_maker() as db:
        for project, host in ((a, "a"), (b, "b")):
            for i in range(6):
                db.add(SitemapUrl(project_id=project.id, url=f"https://{host}.example/p{i}", first_seen_at=NOW, last_seen_at=NOW))
        await db.commit()
        await app_settings.put_setting(db, "inspection_budget", 10, "test")
        await app_settings.put_setting(db, "inspection_budget_split", {a.slug: 2}, "test")
    await jobs.run_url_inspection(async_session_maker, inspect_ok(), now=NOW)
    assert await inspections_count(a) == 2 and await inspections_count(b) == 6


async def test_changed_pages_are_reinspected_before_merely_old_ones():
    project = await make_project()
    await seed_urls(project, "/old", "/changed", "/fresh")
    async with async_session_maker() as db:
        for path, age in (("/old", 20), ("/changed", 10), ("/fresh", 1)):
            db.add(UrlInspection(project_id=project.id, url=f"https://site.example{path}", inspected_at=NOW - timedelta(days=age), verdict="PASS"))
        db.add(PageSignal(project_id=project.id, url="https://site.example/changed", fetched_at=NOW - timedelta(days=2), http_status=200, word_count=500, content_hash="new"))
        await db.commit()
        queue = await jobs.inspection_queue(db, project, NOW)
    assert queue == ["https://site.example/changed", "https://site.example/old"]  # /fresh is inside the 3-day minimum


async def test_inspection_failures_are_isolated_and_quota_stops_the_run():
    a, b = await make_project("a", "https://a.example/", "https://a.example/"), await make_project("b", "https://b.example/", "https://b.example/")
    async with async_session_maker() as db:
        for project, host in ((a, "a"), (b, "b")):
            db.add(SitemapUrl(project_id=project.id, url=f"https://{host}.example/p", first_seen_at=NOW, last_seen_at=NOW))
        await db.commit()
    session = FakeSession(lambda url, body: FakeResponse(status_code=403) if "a.example" in body["siteUrl"] else FakeResponse({"inspectionResult": {"indexStatusResult": {"verdict": "PASS"}}}))
    result = await jobs.run_url_inspection(async_session_maker, session, now=NOW)
    assert result["status"] == "partial"
    assert result["detail"][a.slug]["status"] == "error" and result["detail"][b.slug]["inspected"] == 1

    quota = FakeSession(lambda url, body: FakeResponse(status_code=429))
    await jobs.run_url_inspection(async_session_maker, quota, now=NOW + timedelta(days=5))
    assert len(quota.calls) == 1  # stopped at the first 429


# ---------------------------------------------------------------- read side


async def test_url_statuses_and_snapshot_counts():
    project = await make_project()
    await seed_urls(project, "/idx", "/thin", "/new")
    async with async_session_maker() as db:
        db.add(UrlInspection(project_id=project.id, url="https://site.example/idx", verdict="PASS", coverage_state="Submitted and indexed"))
        db.add(PageSignal(project_id=project.id, url="https://site.example/idx", http_status=200, word_count=900, title="A", content_hash="a"))
        db.add(PageSignal(project_id=project.id, url="https://site.example/thin", http_status=200, word_count=80, title="B", content_hash="b"))
        await db.commit()
        rows = await service.url_statuses(db, project.id, 300)
        by_url = {r["url"]: r["issue"] for r in rows}
        assert by_url == {"https://site.example/idx": "indexed", "https://site.example/thin": "thin", "https://site.example/new": "unknown"}
        counts = await service.record_snapshot(db, project.id, 300)
        assert counts["indexed"] == counts["thin"] == counts["unknown"] == 1
        await service.record_snapshot(db, project.id, 300)  # same day: updates in place
    assert service.indexed_percent({"indexed": 1, "thin": 1, "unknown": 5}) == 50.0
    assert service.indexed_percent({"unknown": 3}) is None


# ---------------------------------------------------------------- settings


async def test_settings_defaults_validation_and_ceiling():
    async with async_session_maker() as db:
        assert (await app_settings.get_all_settings(db))["inspection_budget"] == 500
        assert await app_settings.put_setting(db, "inspection_budget", 1500, "t") == 1500
        for key, bad in [
            ("inspection_budget", 1501), ("inspection_budget", -1), ("inspection_budget", "9"), ("inspection_budget", True),
            ("thin_word_threshold", 10), ("volume_source", "dataforseo"), ("scoring_weights", {"demand": 1}),
            ("scoring_weights", {"demand": 1, "gap": 1, "relevance": 1, "competition": "x"}),
            ("inspection_budget_split", {"a": 5000}), ("llm_daily_cap_usd", 1000), ("nope", 1),
        ]:
            with pytest.raises(app_settings.SettingError):
                await app_settings.put_setting(db, key, bad, "t")
        assert (await app_settings.get_all_settings(db))["inspection_budget"] == 1500
    assert app_settings.effective_budget(99999) == 1500 and app_settings.effective_budget(-5) == 0
