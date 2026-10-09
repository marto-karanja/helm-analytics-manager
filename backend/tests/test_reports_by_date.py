import ast
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from sqlalchemy import delete, select

from app.db.session import async_session_maker
from app.indexing import service
from app.keywords import rollup
from app.keywords.rollup import week_start
from app.models.indexing import (
    GscQueryRollup, KeywordCandidate, PageSignal, SitemapUrl, UrlInspection, UrlStatusHistory, WeeklyDigest,
)
from app.models.project import Project, TrafficDaily, TrafficSnapshot
from app.reports import builders
from app.reports.compare import compare_reports
from tests.fakes import FakeResponse, FakeSession

TODAY = datetime.now(timezone.utc).date()
MONDAY = week_start(TODAY)


def day(n: int, hour: int = 12) -> datetime:
    """`n` days before today at `hour` UTC."""
    return datetime.combine(TODAY - timedelta(days=n), datetime.min.time(), tzinfo=timezone.utc).replace(hour=hour)


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    yield
    async with async_session_maker() as db:
        await db.execute(delete(Project).where(Project.slug.like("rd-%")))
        await db.commit()


async def make_project(pipeline=True, gsc="https://rd.example/") -> Project:
    async with async_session_maker() as db:
        p = Project(slug=f"rd-{uuid.uuid4().hex[:8]}", name=f"RD {uuid.uuid4().hex[:4]}", category="seo-content-site", url="https://rd.example/", is_pipeline=pipeline, gsc_site_url=gsc)
        db.add(p)
        await db.commit()
        return p


INDEXED = dict(verdict="PASS", coverage_state="Submitted and indexed", indexing_state="INDEXING_ALLOWED", page_fetch_state="SUCCESSFUL")
CRAWLED = dict(verdict="NEUTRAL", coverage_state="Crawled - currently not indexed", indexing_state="INDEXING_ALLOWED", page_fetch_state="SUCCESSFUL")


async def seed_timeline(project):
    """/a was in the sitemap 40 days ago and indexed 30 days ago. /b arrived 20 days ago, was crawled-not-indexed 15
    days ago and indexed 5 days ago. /c arrived 20 days ago and left 8 days ago."""
    async with async_session_maker() as db:
        db.add_all([
            SitemapUrl(project_id=project.id, url="https://rd.example/a", first_seen_at=day(40), last_seen_at=day(0)),
            SitemapUrl(project_id=project.id, url="https://rd.example/b", first_seen_at=day(20), last_seen_at=day(0)),
            SitemapUrl(project_id=project.id, url="https://rd.example/c", first_seen_at=day(20), last_seen_at=day(8), removed_at=day(8)),
            UrlInspection(project_id=project.id, url="https://rd.example/a", inspected_at=day(30), **INDEXED),
            UrlInspection(project_id=project.id, url="https://rd.example/b", inspected_at=day(15), **CRAWLED),
            UrlInspection(project_id=project.id, url="https://rd.example/b", inspected_at=day(5), **INDEXED),
            UrlInspection(project_id=project.id, url="https://rd.example/c", inspected_at=day(18), **CRAWLED),
        ])
        await db.commit()


def params(as_of: date, **kw) -> builders.Params:
    return builders.Params(as_of=as_of, today=TODAY, **kw)


async def build(project, name, as_of=None, **kw):
    async with async_session_maker() as db:
        return await builders.build(db, [project], name, params(as_of or TODAY, **kw))


def issue_counts(report) -> dict:
    columns = report.columns
    row = report.rows[0]
    return {c: row[columns.index(c)] for c in columns if c not in ("project",)}


# ---------------------------------------------------------------- history storage


async def test_status_history_records_only_changes_and_is_append_only():
    p = await make_project()
    await seed_timeline(p)
    async with async_session_maker() as db:
        first = await service.record_status_history(db, p.id, 300, now=day(3))
        again = await service.record_status_history(db, p.id, 300, now=day(2))
    assert first == 2 and again == 0  # /a and /b baselines; nothing changed since; /c is not live

    async with async_session_maker() as db:
        db.add(UrlInspection(project_id=p.id, url="https://rd.example/a", inspected_at=day(1), **CRAWLED))
        db.add(SitemapUrl(project_id=p.id, url="https://rd.example/d", first_seen_at=day(1), last_seen_at=day(0)))
        await db.commit()
        changed = await service.record_status_history(db, p.id, 300, now=day(0))
    assert changed == 2  # /a re-inspected with a new result, /d appeared

    async with async_session_maker() as db:
        rows = list((await db.execute(select(UrlStatusHistory).where(UrlStatusHistory.project_id == p.id).order_by(UrlStatusHistory.valid_from))).scalars())
        sitemap = (await db.execute(select(SitemapUrl).where(SitemapUrl.project_id == p.id, SitemapUrl.url == "https://rd.example/b"))).scalar_one()
        sitemap.removed_at = day(0)
        await db.commit()
        removed = await service.record_status_history(db, p.id, 300, now=day(0, 13))
        after = list((await db.execute(select(UrlStatusHistory).where(UrlStatusHistory.project_id == p.id))).scalars())
    assert len(rows) == 4 and removed == 1 and len(after) == 5  # earlier rows untouched, one removal marker added
    assert [r for r in after if r.url.endswith("/b") and r.issue is None]


async def test_stored_history_is_what_was_shown_even_after_the_rules_change():
    p = await make_project()
    await seed_timeline(p)
    async with async_session_maker() as db:
        db.add(PageSignal(project_id=p.id, url="https://rd.example/a", fetched_at=day(3), http_status=200, title="A", word_count=100))
        await db.commit()
        await service.record_status_history(db, p.id, 300, now=day(2))  # threshold 300: 100 words is thin
        shown_then, basis = await service.status_as_of(db, p.id, 300, service.end_of_day(TODAY - timedelta(days=1)))
        after_rule_change, basis_after = await service.status_as_of(db, p.id, 50, service.end_of_day(TODAY - timedelta(days=1)))
        fresh_with_new_rule = await service.url_statuses(db, p.id, 50)
    by_url = lambda rows: {r["url"]: r["issue"] for r in rows}
    assert basis == basis_after == "stored"
    assert by_url(shown_then) == by_url(after_rule_change)  # the stored rows do not move
    assert by_url(shown_then)["https://rd.example/a"] != by_url(fresh_with_new_rule)["https://rd.example/a"]  # today's rules would differ


async def test_before_history_starts_the_status_is_reconstructed_from_inspections():
    p = await make_project()
    await seed_timeline(p)
    async with async_session_maker() as db:
        await service.record_status_history(db, p.id, 300, now=day(2))
        rows, basis = await service.status_as_of(db, p.id, 300, service.end_of_day(TODAY - timedelta(days=16)))  # before history
        later, later_basis = await service.status_as_of(db, p.id, 300, service.end_of_day(TODAY))
    assert basis == "reconstructed" and later_basis == "stored"
    by_url = {r["url"]: r["issue"] for r in rows}
    assert by_url == {"https://rd.example/a": "indexed", "https://rd.example/b": "unknown", "https://rd.example/c": "crawled_not_indexed"}


async def test_reconstruction_follows_the_inspection_and_sitemap_timeline():
    p = await make_project()
    await seed_timeline(p)
    async with async_session_maker() as db:
        def at(n):
            return service.end_of_day(TODAY - timedelta(days=n))

        async def issues(n):
            return {r["url"].rsplit("/", 1)[1]: r["issue"] for r in await service.url_statuses(db, p.id, 300, at(n))}

        assert await issues(35) == {"a": "unknown"}  # /a is in the sitemap but not inspected yet
        assert await issues(29) == {"a": "indexed"}
        assert await issues(16) == {"a": "indexed", "b": "unknown", "c": "crawled_not_indexed"}  # /b arrived but is not inspected yet
        assert await issues(14) == {"a": "indexed", "b": "crawled_not_indexed", "c": "crawled_not_indexed"}
        assert await issues(6) == {"a": "indexed", "b": "crawled_not_indexed"}  # /c left on day 8
        assert await issues(4) == {"a": "indexed", "b": "indexed"}  # /b was re-inspected on day 5


# ---------------------------------------------------------------- the indexing report by date


async def test_indexing_report_by_date_with_basis_and_out_of_range_note():
    p = await make_project()
    await seed_timeline(p)
    current = await build(p, "indexing")
    assert current.meta["basis"] == "current" and issue_counts(current)["indexed"] == 2

    past = await build(p, "indexing", TODAY - timedelta(days=29))
    assert past.meta["basis"] == "reconstructed" and "Reconstructed" in past.meta["note"]
    assert issue_counts(past)["total_urls"] == 1 and issue_counts(past)["indexed"] == 1

    too_early = await build(p, "indexing", TODAY - timedelta(days=60))
    assert too_early.rows == [] and too_early.meta["out_of_range"] is True
    assert too_early.meta["available_from"] == TODAY - timedelta(days=40)
    assert "history begins on" in too_early.meta["note"]  # never an empty table that looks like zeros


async def test_a_date_equal_to_today_matches_the_current_report():
    p = await make_project()
    await seed_timeline(p)
    assert (await build(p, "indexing", TODAY)).rows == (await build(p, "indexing")).rows
    assert (await build(p, "non-indexed", TODAY)).rows == (await build(p, "non-indexed")).rows


async def test_non_indexed_and_all_urls_reports_by_date():
    p = await make_project()
    await seed_timeline(p)
    non_indexed = await build(p, "non-indexed", TODAY - timedelta(days=14))
    assert [r[1] for r in non_indexed.rows] == ["https://rd.example/b", "https://rd.example/c"]  # both were crawled but not indexed then
    urls = await build(p, "urls", TODAY - timedelta(days=14))
    assert [r[1] for r in urls.rows] == ["https://rd.example/a", "https://rd.example/b", "https://rd.example/c"]
    assert (await build(p, "urls")).rows and len((await build(p, "urls")).rows) == 2


# ---------------------------------------------------------------- query-based reports


async def seed_rollups(project):
    rows = []
    for k in range(1, 7):
        w = MONDAY - timedelta(weeks=k)
        rows += [
            GscQueryRollup(project_id=project.id, week_start=w, query="alpha tips", page="https://rd.example/a", clicks=2, impressions=100, position_avg=11.0 + k),
            GscQueryRollup(project_id=project.id, week_start=w, query="shared term", page="https://rd.example/a", clicks=1, impressions=60, position_avg=9.0),
            GscQueryRollup(project_id=project.id, week_start=w, query="shared term", page="https://rd.example/b", clicks=1, impressions=50, position_avg=14.0),
        ]
    async with async_session_maker() as db:
        db.add_all(rows)
        await db.commit()


async def test_striking_distance_and_cannibalisation_as_of_a_date():
    p = await make_project()
    await seed_rollups(p)
    now = await build(p, "striking-distance")
    assert {r[1] for r in now.rows} == {"alpha tips", "shared term"}
    early = await build(p, "striking-distance", MONDAY - timedelta(weeks=5, days=-1))  # only weeks 6 and older are before it
    assert early.meta["out_of_range"] is False  # data exists for that date
    way_before = await build(p, "striking-distance", MONDAY - timedelta(weeks=10))
    assert way_before.rows == [] and way_before.meta["out_of_range"] is True and "history begins" in way_before.meta["note"]
    cannibal = await build(p, "cannibalisation")
    assert [r[1] for r in cannibal.rows] == ["shared term"] and cannibal.rows[0][2] == 2


async def test_rankings_report_uses_only_weeks_that_had_ended_by_the_date():
    p = await make_project()
    await seed_rollups(p)
    # As of the Sunday that ends week k=3 the window is weeks k=6..3. Page /a ranks for "alpha tips" (position 11+k,
    # 100 impressions a week) and "shared term" (position 9, 60 a week): (4*11*100 + 18*100 + 4*9*60) / 640 = 13.1.
    sunday = MONDAY - timedelta(weeks=2, days=1)
    report = await build(p, "rankings", sunday)
    alpha = next(r for r in report.rows if r[1] == "https://rd.example/a")
    assert alpha[2] == 13.1 and alpha[3] is None  # no weeks before k=6, so no prior position
    # Without a date the window is the newest weeks k=4..1: (4400 + 10*100 + 2160) / 640 = 11.8, and k=8..5 is the prior window.
    latest = await build(p, "rankings")
    latest_alpha = next(r for r in latest.rows if r[1] == "https://rd.example/a")
    assert latest_alpha[2] == 11.8 and latest_alpha[3] is not None and latest_alpha[4] > 0  # moved up from the prior window


# ---------------------------------------------------------------- traffic, alerts, keywords, digest


async def test_traffic_range_report_and_granularity():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([TrafficDaily(project_id=p.id, metric_date=TODAY - timedelta(days=i), clicks=10, impressions=100, avg_position=8.0, sessions=5) for i in range(1, 61)])
        await db.commit()
    total = await build(p, "traffic", TODAY - timedelta(days=1), days=28)
    assert len(total.rows) == 1 and total.rows[0][3:] == [280, 2800, 0.1, 8.0, 140]
    weekly = await build(p, "traffic", TODAY - timedelta(days=1), days=28, granularity="week")
    assert 4 <= len(weekly.rows) <= 5 and sum(r[3] for r in weekly.rows) == 280
    monthly = await build(p, "traffic", TODAY - timedelta(days=1), days=60, granularity="month")
    assert sum(r[3] for r in monthly.rows) == 600
    daily = await build(p, "traffic", TODAY - timedelta(days=1), days=7, granularity="day")
    assert len(daily.rows) == 7
    before = await build(p, "traffic", TODAY - timedelta(days=90))
    assert before.rows == [] and before.meta["out_of_range"] is True


async def test_alerts_report_shows_the_saved_state_on_that_date():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([
            TrafficSnapshot(project_id=p.id, synced_at=day(10), configured=True, alert_severity="red", alert_messages=[{"kind": "zero_impressions", "severity": "red", "message": "Zero impressions"}]),
            TrafficSnapshot(project_id=p.id, synced_at=day(3), configured=True, alert_severity="green", alert_messages=[]),
        ])
        await db.commit()
    assert [r[3] for r in (await build(p, "alerts", TODAY - timedelta(days=5))).rows] == ["Zero impressions"]
    assert (await build(p, "alerts", TODAY)).rows == []  # cleared since
    assert (await build(p, "alerts", TODAY - timedelta(days=30))).meta["out_of_range"] is True


async def test_keywords_report_shows_the_status_it_had_on_the_date():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([
            KeywordCandidate(project_id=p.id, keyword="old and accepted", status="accepted", created_at=day(20), decided_at=day(5), score=3.0),
            KeywordCandidate(project_id=p.id, keyword="newer", status="proposed", created_at=day(2), score=1.0),
        ])
        await db.commit()
    long_ago = {r[1]: r[2] for r in (await build(p, "keywords", TODAY - timedelta(days=10))).rows}
    assert long_ago == {"old and accepted": "proposed"}  # not yet decided, and "newer" did not exist
    now = {r[1]: r[2] for r in (await build(p, "keywords")).rows}
    assert now == {"old and accepted": "accepted", "newer": "proposed"}


async def test_digest_report_lists_only_weeks_that_had_ended_by_the_date():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([WeeklyDigest(project_id=p.id, week_start=MONDAY - timedelta(weeks=k), payload={"traffic": {"clicks": 100 * k}}) for k in range(1, 6)])
        await db.commit()
    assert len((await build(p, "digest")).rows) == 5
    as_of = MONDAY - timedelta(weeks=2, days=1)  # the Sunday ending week k=3
    weeks = [r[1] for r in (await build(p, "digest", as_of)).rows]
    assert weeks[0] == MONDAY - timedelta(weeks=3) and len(weeks) == 3
    latest = await build(p, "digest", as_of, latest_week_only=True)
    assert [r[1] for r in latest.rows] == [MONDAY - timedelta(weeks=3)]


# ---------------------------------------------------------------- compare


async def test_compare_labels_new_gone_changed_and_same_with_deltas():
    p = await make_project()
    await seed_timeline(p)
    a = await build(p, "urls", TODAY - timedelta(days=14))
    b = await build(p, "urls", TODAY)
    result = compare_reports(a, b, ("project", "url"))
    status = {row[1].rsplit("/", 1)[1]: row[2] for row in result["rows"]}
    assert status == {"a": "same", "b": "changed", "c": "gone"}
    assert result["summary"] == {"new": 0, "gone": 1, "changed": 1, "same": 1}
    changed_only = compare_reports(a, b, ("project", "url"), changed_only=True)
    assert {r[1].rsplit("/", 1)[1] for r in changed_only["rows"]} == {"b", "c"}

    idx_a, idx_b = await build(p, "indexing", TODAY - timedelta(days=14)), await build(p, "indexing")
    comparison = compare_reports(idx_a, idx_b, ("project",))
    columns, row = comparison["columns"], comparison["rows"][0]
    assert row[columns.index("change")] == "changed"
    assert row[columns.index("indexed_a")] == 1 and row[columns.index("indexed_b")] == 2 and row[columns.index("indexed_delta")] == 1


async def test_compare_two_traffic_periods():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([TrafficDaily(project_id=p.id, metric_date=TODAY - timedelta(days=i), clicks=10 if i > 14 else 30, impressions=100, avg_position=8.0) for i in range(1, 29)])
        await db.commit()
    a = await build(p, "traffic", TODAY - timedelta(days=15), days=14)
    b = await build(p, "traffic", TODAY - timedelta(days=1), days=14)
    result = compare_reports(a, b, ("project",))
    columns, row = result["columns"], result["rows"][0]
    assert row[columns.index("clicks_a")] == 140 and row[columns.index("clicks_b")] == 420 and row[columns.index("clicks_delta")] == 280


async def test_compare_alerts_shows_new_and_cleared():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([
            TrafficSnapshot(project_id=p.id, synced_at=day(10), configured=True, alert_severity="red", alert_messages=[{"kind": "zero_impressions", "severity": "red", "message": "Zero impressions"}]),
            TrafficSnapshot(project_id=p.id, synced_at=day(2), configured=True, alert_severity="yellow", alert_messages=[{"kind": "no_data", "severity": "yellow", "message": "No data"}]),
        ])
        await db.commit()
    result = compare_reports(await build(p, "alerts", TODAY - timedelta(days=5)), await build(p, "alerts"), ("project", "message"))
    assert {row[1]: row[2] for row in result["rows"]} == {"Zero impressions": "gone", "No data": "new"}


# ---------------------------------------------------------------- over HTTP


async def test_reports_api_dates_compare_csv_availability_and_catalog(auth_client):
    p = await make_project()
    await seed_timeline(p)
    slug = p.slug

    catalog = (await auth_client.get("/api/reports/catalog")).json()
    assert [r["name"] for r in catalog["reports"]] == ["indexing", "non-indexed", "urls", "rankings", "striking-distance", "cannibalisation", "traffic", "alerts", "keywords", "digest"]

    past = await auth_client.get("/api/reports/indexing", params={"project": slug, "as_of": (TODAY - timedelta(days=29)).isoformat()})
    assert past.status_code == 200 and past.json()["meta"]["basis"] == "reconstructed" and past.json()["rows"][0][1] == 1

    assert (await auth_client.get("/api/reports/indexing", params={"project": slug, "as_of": (TODAY + timedelta(days=2)).isoformat()})).status_code == 422
    assert (await auth_client.get("/api/reports/indexing", params={"project": slug, "as_of": (TODAY + timedelta(days=1)).isoformat()})).status_code == 200  # a reader east of UTC
    assert (await auth_client.get("/api/reports/traffic", params={"project": slug, "granularity": "yearly"})).status_code == 422
    assert (await auth_client.get("/api/reports/nope/compare", params={"a": TODAY.isoformat(), "b": TODAY.isoformat()})).status_code == 404

    cmp_ = await auth_client.get("/api/reports/urls/compare", params={"project": slug, "a": (TODAY - timedelta(days=14)).isoformat(), "b": TODAY.isoformat()})
    body = cmp_.json()
    assert cmp_.status_code == 200 and body["summary"] == {"new": 0, "gone": 1, "changed": 1, "same": 1} and body["meta"]["a"]["basis"] == "reconstructed"
    csv = await auth_client.get("/api/reports/urls/compare", params={"project": slug, "a": (TODAY - timedelta(days=14)).isoformat(), "b": TODAY.isoformat(), "format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv") and f"{(TODAY - timedelta(days=14)).isoformat()}" in csv.headers["content-disposition"]
    assert csv.text.splitlines()[0].startswith("project,url,change")

    avail = (await auth_client.get("/api/reports/availability", params={"project": slug})).json()
    assert avail["today"] == TODAY.isoformat() and avail["reports"]["indexing"]["from"] == (TODAY - timedelta(days=40)).isoformat()
    assert avail["reports"]["traffic"]["from"] is None  # no traffic rows for this project
    assert (await auth_client.get("/api/reports/availability", params={"project": "missing"})).status_code == 404


async def test_demo_user_sees_only_demo_projects_in_dated_reports(client):
    p = await make_project()
    await seed_timeline(p)
    token = (await client.post("/api/auth/demo-login")).json()["access_token"]
    headers = {"authorization": f"Bearer {token}"}
    report = (await client.get("/api/reports/indexing", params={"as_of": (TODAY - timedelta(days=29)).isoformat()}, headers=headers)).json()
    assert p.name not in [row[0] for row in report["rows"]]
    assert (await client.get("/api/reports/indexing", params={"project": p.slug}, headers=headers)).status_code == 404


# ---------------------------------------------------------------- storage guarantees


def test_nothing_in_the_app_deletes_from_a_history_table():
    """History is kept indefinitely. Only the demo reseed deletes, and only demo rows."""
    history = {
        "TrafficDaily", "TrafficSnapshot", "GscQueryRollup", "UrlInspection", "PageSignal", "SitemapUrl", "UrlStatusHistory",
        "IndexingSnapshot", "WeeklyDigest", "AlertEvent", "CollectorRun", "KeywordCandidate", "KeywordRun",
    }
    offenders = []
    for path in (Path(__file__).resolve().parent.parent / "app").rglob("*.py"):
        if path.name == "demo_seed.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in {"delete", "truncate"}:
                    args = {getattr(a, "id", None) for a in node.args} | {getattr(a, "attr", None) for a in node.args}
                    if args & history:
                        offenders.append(f"{path.name}: {name}({', '.join(sorted(a for a in args if a))})")
    assert not offenders, offenders


async def test_a_deep_rollup_backfill_reaches_back_further_than_the_refresh_window():
    p = await make_project()
    calls = []

    def respond(url, body):
        calls.append(body["startDate"])
        return FakeResponse({"rows": []})

    today = date(2026, 10, 9)
    await rollup.run_gsc_query_rollup(async_session_maker, FakeSession(respond), today=today)  # a first pull
    first_start = date.fromisoformat(calls[-1])
    async with async_session_maker() as db:
        db.add(GscQueryRollup(project_id=p.id, week_start=date(2026, 9, 28), query="q", page="https://rd.example/a", clicks=1, impressions=1, position_avg=1.0))
        await db.commit()
    await rollup.run_gsc_query_rollup(async_session_maker, FakeSession(respond), today=today)  # has rows: the short refresh
    refresh_start = date.fromisoformat(calls[-1])
    await rollup.run_gsc_query_rollup(async_session_maker, FakeSession(respond), today=today, backfill_days=480)
    deep_start = date.fromisoformat(calls[-1])
    assert (today - first_start).days >= 470 and (today - refresh_start).days < 60 and (today - deep_start).days >= 470
    assert rollup.BACKFILL_DAYS == 480
