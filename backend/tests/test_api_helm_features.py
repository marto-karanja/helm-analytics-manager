import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.keywords import launch as launch_mod
from app.core import mcp_tokens
from app.core.config import settings
from app.core.csv_export import to_csv
from app.db.session import async_session_maker
from app.keywords import generator
from app.models.indexing import (
    AppSetting,
    GscQueryRollup,
    IndexingSnapshot,
    InspectRequest,
    KeywordCandidate,
    KeywordRun,
    McpCall,
    McpToken,
    PageSignal,
    SitemapStatus,
    SitemapUrl,
    UrlInspection,
    WeeklyDigest,
)
from app.models.project import Project

NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture(autouse=True)
async def isolated():
    async with async_session_maker() as db:
        await db.execute(update(Project).values(is_pipeline=False))
        for model in (AppSetting, KeywordCandidate, KeywordRun, GscQueryRollup, WeeklyDigest, PageSignal, SitemapUrl, UrlInspection, InspectRequest, SitemapStatus, IndexingSnapshot, McpToken, McpCall):
            await db.execute(delete(model))
        await db.commit()


async def make_project(gsc="https://api.example/", demo=False, name="Api Site") -> Project:
    async with async_session_maker() as db:
        project = Project(
            slug=f"api-{uuid.uuid4().hex[:8]}", name=name, category="seo-content-site", url="https://api.example/",
            is_pipeline=True, gsc_site_url=gsc, is_demo=demo,
        )
        db.add(project)
        await db.commit()
        return project


async def seed_site(project):
    async with async_session_maker() as db:
        for path in ("idx", "thin", "new"):
            db.add(SitemapUrl(project_id=project.id, url=f"https://api.example/{path}", source_sitemap="https://api.example/sitemap.xml"))
        db.add(UrlInspection(project_id=project.id, url="https://api.example/idx", verdict="PASS", coverage_state="Submitted and indexed", page_fetch_state="SUCCESSFUL"))
        db.add(PageSignal(project_id=project.id, url="https://api.example/idx", http_status=200, word_count=900, title="Idx page", content_hash="a"))
        db.add(PageSignal(project_id=project.id, url="https://api.example/thin", http_status=200, word_count=40, title="Thin page", content_hash="b"))
        db.add(IndexingSnapshot(project_id=project.id, snapshot_date=date.today() - timedelta(days=1), total_urls=3, counts={"indexed": 1}))
        await db.commit()


@pytest_asyncio.fixture
async def demo_client(client):
    response = await client.post("/api/auth/demo-login")
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client


# ---------------------------------------------------------------- indexing


async def test_indexing_summary_and_url_list(auth_client):
    project = await make_project()
    await seed_site(project)
    summary = (await auth_client.get(f"/api/projects/{project.id}/indexing")).json()
    assert summary["total"] == 3 and summary["counts"]["indexed"] == 1 and summary["counts"]["thin"] == 1 and summary["counts"]["unknown"] == 1
    assert summary["indexed_percent"] == 50.0 and summary["budget"]["budget"] == 500 and summary["has_search_console"] is True
    assert summary["history"][0]["counts"] == {"indexed": 1}

    listed = (await auth_client.get(f"/api/projects/{project.id}/indexing/urls", params={"issue": "thin"})).json()
    assert listed["total"] == 1 and listed["items"][0]["url"].endswith("/thin") and listed["items"][0]["word_count"] == 40
    searched = (await auth_client.get(f"/api/projects/{project.id}/indexing/urls", params={"q": "IDX", "limit": 1})).json()
    assert searched["total"] == 1
    assert (await auth_client.get(f"/api/projects/{project.id}/indexing/urls", params={"issue": "bogus"})).status_code == 422
    assert (await auth_client.get(f"/api/projects/{project.id}/indexing/urls", params={"limit": 9999})).status_code == 422


async def test_url_detail_returns_history_and_404s_for_other_projects(auth_client):
    project, other = await make_project(), await make_project()
    await seed_site(project)
    items = (await auth_client.get(f"/api/projects/{project.id}/indexing/urls", params={"q": "idx"})).json()["items"]
    detail = (await auth_client.get(f"/api/projects/{project.id}/indexing/urls/{items[0]['id']}")).json()
    assert detail["issue"] == "indexed" and detail["inspections"][0]["verdict"] == "PASS" and detail["signals"][0]["word_count"] == 900
    assert (await auth_client.get(f"/api/projects/{other.id}/indexing/urls/{items[0]['id']}")).status_code == 404
    assert (await auth_client.get(f"/api/projects/{uuid.uuid4()}/indexing")).status_code == 404


async def test_inspect_now_queues_validates_and_counts_against_the_budget(auth_client):
    project = await make_project()
    await seed_site(project)
    url = f"/api/projects/{project.id}/indexing/inspect"
    ok = await auth_client.post(url, json={"url": "https://api.example/idx"})
    assert ok.status_code == 202 and ok.json()["budget"]["remaining"] == 498  # 1 spent by the seeded inspection, 1 now queued
    assert (await auth_client.post(url, json={"url": "https://api.example/idx"})).status_code == 409  # already queued
    assert (await auth_client.post(url, json={"url": "https://elsewhere.example/x"})).status_code == 404  # not in the sitemap
    async with async_session_maker() as db:
        db.add(AppSetting(key="inspection_budget", value=1))
        await db.commit()
    assert (await auth_client.post(url, json={"url": "https://api.example/thin"})).status_code == 429  # budget used up
    no_gsc = await make_project(gsc=None)
    assert (await auth_client.post(f"/api/projects/{no_gsc.id}/indexing/inspect", json={"url": "x"})).status_code == 409


async def test_sitemaps_endpoint(auth_client):
    project = await make_project()
    await seed_site(project)
    async with async_session_maker() as db:
        db.add(SitemapStatus(project_id=project.id, path="https://api.example/sitemap.xml", is_pending=True, errors=0, warnings=2, submitted_urls=3, last_downloaded=NOW))
        await db.commit()
    body = (await auth_client.get(f"/api/projects/{project.id}/sitemaps")).json()
    assert body["sitemaps"][0]["warnings"] == 2 and body["sitemaps"][0]["urls_found_by_helm"] == 3
    assert body["urls_by_source"] == [{"sitemap": "https://api.example/sitemap.xml", "urls": 3}]


async def test_demo_account_reads_demo_projects_only_and_cannot_write(demo_client):
    demo = await make_project(demo=True, name="Demo")
    real = await make_project()
    await seed_site(demo)
    assert (await demo_client.get(f"/api/projects/{demo.id}/indexing")).status_code == 200
    assert (await demo_client.get(f"/api/projects/{real.id}/indexing")).status_code == 404
    assert (await demo_client.post(f"/api/projects/{demo.id}/indexing/inspect", json={"url": "https://api.example/idx"})).status_code == 403
    assert (await demo_client.put("/api/settings/inspection_budget", json={"value": 5})).status_code == 403
    assert (await demo_client.get("/api/mcp-tokens")).status_code == 403
    assert (await demo_client.post(f"/api/projects/{demo.id}/keywords/runs")).status_code == 403


async def test_endpoints_require_login(client):
    for path in ("/api/settings", "/api/reports/indexing", f"/api/projects/{uuid.uuid4()}/indexing", "/api/mcp-tokens"):
        assert (await client.get(path)).status_code == 401


# ---------------------------------------------------------------- keywords


async def seed_candidates(project):
    async with async_session_maker() as db:
        rows = [
            KeywordCandidate(project_id=project.id, keyword="alpha", score=50.0, status="proposed", intent="informational"),
            KeywordCandidate(project_id=project.id, keyword="beta", score=70.0, status="proposed"),
            KeywordCandidate(project_id=project.id, keyword="gamma", score=10.0, status="accepted", target_url="https://api.example/g"),
        ]
        db.add_all(rows)
        await db.commit()
        return {r.keyword: r.id for r in rows}


async def test_keyword_list_orders_by_score_and_counts(auth_client):
    project = await make_project()
    await seed_candidates(project)
    body = (await auth_client.get(f"/api/projects/{project.id}/keywords")).json()
    assert [c["keyword"] for c in body["candidates"]] == ["beta", "alpha", "gamma"]
    assert body["counts"] == {"proposed": 2, "accepted": 1, "rejected": 0, "written": 0}
    only = (await auth_client.get(f"/api/projects/{project.id}/keywords", params={"status": "accepted"})).json()
    assert [c["keyword"] for c in only["candidates"]] == ["gamma"]
    assert (await auth_client.get(f"/api/projects/{project.id}/keywords", params={"status": "nope"})).status_code == 422


async def test_accept_reject_bulk_and_the_written_lock(auth_client):
    project = await make_project()
    ids = await seed_candidates(project)
    accepted = await auth_client.patch(f"/api/keywords/{ids['alpha']}", json={"status": "accepted"})
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted" and accepted.json()["decided_at"]
    reopened = await auth_client.patch(f"/api/keywords/{ids['alpha']}", json={"status": "proposed"})
    assert reopened.json()["decided_at"] is None
    assert (await auth_client.patch(f"/api/keywords/{ids['alpha']}", json={"status": "written"})).status_code == 422  # clients cannot mark written
    assert (await auth_client.patch(f"/api/keywords/{uuid.uuid4()}", json={"status": "rejected"})).status_code == 404

    bulk = await auth_client.post(f"/api/projects/{project.id}/keywords/bulk", json={"ids": [str(ids["alpha"]), str(ids["beta"])], "status": "rejected"})
    assert bulk.json() == {"updated": 2}
    assert (await auth_client.post(f"/api/projects/{project.id}/keywords/bulk", json={"ids": [], "status": "rejected"})).status_code == 422

    async with async_session_maker() as db:
        row = await db.get(KeywordCandidate, ids["gamma"])
        row.status = "written"
        await db.commit()
    assert (await auth_client.patch(f"/api/keywords/{ids['gamma']}", json={"status": "rejected"})).status_code == 409
    again = await auth_client.post(f"/api/projects/{project.id}/keywords/bulk", json={"ids": [str(ids["gamma"])], "status": "rejected"})
    assert again.json() == {"updated": 0}


async def test_export_endpoint_writes_file_and_marks_written(auth_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "keyword_export_dir", str(tmp_path))
    project = await make_project()
    await seed_candidates(project)
    body = (await auth_client.post(f"/api/projects/{project.id}/keywords/export")).json()
    assert body["count"] == 1 and body["queue"]["keywords"][0]["keyword"] == "gamma" and body["queue"]["keywords"][0]["action"] == "improve"
    assert json.loads((tmp_path / project.slug / "keyword_queue.json").read_text())["project"] == project.slug
    after = (await auth_client.get(f"/api/projects/{project.id}/keywords")).json()
    assert after["counts"]["written"] == 1


async def test_start_run_requires_a_key_then_runs_in_the_background(auth_client, monkeypatch):
    project = await make_project()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert (await auth_client.post(f"/api/projects/{project.id}/keywords/runs")).status_code == 409

    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    started = []

    async def fake_execute(session_factory, run_id, **kwargs):
        started.append(run_id)

    monkeypatch.setattr(generator, "execute_run", fake_execute)
    response = await auth_client.post(f"/api/projects/{project.id}/keywords/runs")
    assert response.status_code == 202 and response.json()["status"] == "running"
    for task in list(launch_mod.running):
        await task
    assert started == [uuid.UUID(response.json()["id"])]
    assert (await auth_client.post(f"/api/projects/{project.id}/keywords/runs")).status_code == 409  # one at a time

    async with async_session_maker() as db:
        from app.models.indexing import LlmSpend

        await db.execute(delete(KeywordRun))
        db.add(LlmSpend(model="claude-opus-5-5", cost_usd=99.0))
        await db.commit()
    assert (await auth_client.post(f"/api/projects/{project.id}/keywords/runs")).status_code == 429  # daily cap
    async with async_session_maker() as db:
        await db.execute(delete(LlmSpend))
        await db.commit()


async def test_striking_distance_endpoint(auth_client):
    project = await make_project()
    last_week = date.today() - timedelta(days=date.today().weekday() + 7)
    async with async_session_maker() as db:
        db.add(GscQueryRollup(project_id=project.id, week_start=last_week, query="near miss", page="https://api.example/n", impressions=120, position_avg=12.5, clicks=2))
        db.add(GscQueryRollup(project_id=project.id, week_start=last_week, query="winner", page="https://api.example/w", impressions=900, position_avg=1.5, clicks=300))
        await db.commit()
    rows = (await auth_client.get(f"/api/projects/{project.id}/keywords/striking-distance")).json()
    assert [r["query"] for r in rows] == ["near miss"] and rows[0]["position"] == 12.5


# ---------------------------------------------------------------- reports


async def test_reports_json_and_csv(auth_client):
    project = await make_project(name="Report Site")
    await seed_site(project)
    last_week = date.today() - timedelta(days=date.today().weekday() + 7)
    async with async_session_maker() as db:
        db.add(GscQueryRollup(project_id=project.id, week_start=last_week, query='=HYPERLINK("http://evil")', page="https://api.example/n", impressions=120, position_avg=12.0, clicks=2))
        db.add(WeeklyDigest(project_id=project.id, week_start=last_week, payload={"traffic": {"clicks": 10, "clicks_change_pct": 5.0, "impressions": 100, "impressions_change_pct": -2.0}, "indexing": {"indexed_percent": 50.0}, "striking_distance": 1, "pending_keyword_candidates": 4}))
        await db.commit()

    indexing = (await auth_client.get("/api/reports/indexing", params={"project": project.slug})).json()
    assert indexing["rows"][0][0] == "Report Site" and indexing["rows"][0][1] == 3

    non_indexed = (await auth_client.get("/api/reports/non-indexed", params={"project": project.slug})).json()
    assert [r[2] for r in non_indexed["rows"]] == ["thin"]

    striking = await auth_client.get("/api/reports/striking-distance", params={"project": project.slug, "format": "csv"})
    assert striking.headers["content-type"].startswith("text/csv") and "attachment" in striking.headers["content-disposition"]
    lines = striking.text.strip().split("\r\n")
    assert lines[0] == "project,query,page,position,impressions,clicks"
    assert "'=HYPERLINK" in lines[1]  # formula-looking query text is neutralised

    digest = (await auth_client.get("/api/reports/digest", params={"project": project.slug})).json()
    assert digest["rows"][0][2] == 10 and digest["rows"][0][8] == 4
    week = (await auth_client.get(f"/api/reports/digest/{project.slug}/{last_week.isoformat()}")).json()
    assert week["striking_distance"] == 1
    assert (await auth_client.get(f"/api/reports/digest/{project.slug}/2020-01-06")).status_code == 404

    assert (await auth_client.get("/api/reports/nope")).status_code == 404
    assert (await auth_client.get("/api/reports/indexing", params={"project": "missing"})).status_code == 404
    assert (await auth_client.get("/api/reports/indexing", params={"format": "xml"})).status_code == 422


def test_csv_escaping_quotes_commas_newlines_and_formulas():
    out = to_csv(["a", "b"], [['he said "hi", ok', "line1\nline2"], ["=1+1", "-5"], ["+SUM(A1)", "@cmd"], [None, True], [datetime(2026, 10, 3), 0]])
    lines = out.split("\r\n")
    assert lines[1].startswith('"he said ""hi"", ok","line1\nline2"')
    assert lines[2] == "'=1+1,-5"  # formula neutralised; the quote is not added to a plain negative number below
    assert "'+SUM(A1),'@cmd" in out
    assert ",true" in out and "2026-10-03T00:00:00,0" in out


# ---------------------------------------------------------------- settings and tokens


async def test_settings_read_write_and_validation(auth_client):
    body = (await auth_client.get("/api/settings")).json()
    assert body["values"]["inspection_budget"] == 500 and body["limits"]["inspection_ceiling"] == 1500 and body["editable"] is True
    assert (await auth_client.put("/api/settings/inspection_budget", json={"value": 800})).json() == {"key": "inspection_budget", "value": 800}
    assert (await auth_client.get("/api/settings")).json()["values"]["inspection_budget"] == 800
    over = await auth_client.put("/api/settings/inspection_budget", json={"value": 1501})
    assert over.status_code == 422 and "between 0 and 1500" in over.json()["detail"]
    assert (await auth_client.put("/api/settings/volume_source", json={"value": "keyword_planner"})).status_code == 200
    assert (await auth_client.put("/api/settings/volume_source", json={"value": "dataforseo"})).status_code == 422
    assert (await auth_client.put("/api/settings/unknown_key", json={"value": 1})).status_code == 422
    weights = {"demand": 1, "gap": 2, "relevance": 0.5, "competition": 0.1}
    assert (await auth_client.put("/api/settings/scoring_weights", json={"value": weights})).status_code == 200


async def test_token_lifecycle_the_secret_is_shown_once_and_stored_hashed(auth_client):
    created = (await auth_client.post("/api/mcp-tokens", json={"label": "claude-code", "scope": "read"})).json()
    raw = created["token"]
    assert raw.startswith("helm_") and created["scope"] == "read"
    listed = (await auth_client.get("/api/mcp-tokens")).json()
    assert listed[0]["label"] == "claude-code" and "token" not in listed[0] and "token_hash" not in listed[0]
    async with async_session_maker() as db:
        stored = (await db.execute(select(McpToken))).scalar_one()
        assert stored.token_hash == mcp_tokens.hash_token(raw) and raw not in stored.token_hash
        assert (await mcp_tokens.verify_token(db, raw)).label == "claude-code"
        assert await mcp_tokens.verify_token(db, "helm_wrong") is None and await mcp_tokens.verify_token(db, None) is None
    assert (await auth_client.get("/api/mcp-tokens")).json()[0]["last_used_at"] is not None

    assert (await auth_client.post("/api/mcp-tokens", json={"label": "", "scope": "read"})).status_code == 422
    assert (await auth_client.post("/api/mcp-tokens", json={"label": "x", "scope": "admin"})).status_code == 422
    assert (await auth_client.delete(f"/api/mcp-tokens/{created['id']}")).status_code == 204
    async with async_session_maker() as db:
        assert await mcp_tokens.verify_token(db, raw) is None  # revoked tokens stop working
    assert (await auth_client.delete(f"/api/mcp-tokens/{uuid.uuid4()}")).status_code == 404


def test_scope_and_rate_limit_rules():
    read, write = McpToken(label="r", scope="read", token_hash="a"), McpToken(label="w", scope="write", token_hash="b")
    assert mcp_tokens.allows(read, "read") and not mcp_tokens.allows(read, "write")
    assert mcp_tokens.allows(write, "read") and mcp_tokens.allows(write, "write")
    clock = {"t": 0.0}
    limiter = mcp_tokens.RateLimiter(per_minute=3, clock=lambda: clock["t"])
    assert [limiter.allow("k") for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("other")  # separate keys do not share a window
    clock["t"] = 61.0
    assert limiter.allow("k")


async def test_keyword_queue_pull_needs_a_valid_token(client, auth_client):
    project = await make_project()
    await seed_candidates(project)
    token = (await auth_client.post("/api/mcp-tokens", json={"label": "pipeline", "scope": "read"})).json()["token"]
    plain = client  # same client object; drop the browser JWT so only the bearer token counts
    plain.headers["Authorization"] = f"Bearer {token}"
    ok = await plain.get(f"/api/keyword-queue/{project.slug}")
    assert ok.status_code == 200 and [k["keyword"] for k in ok.json()["keywords"]] == ["gamma"]
    plain.headers["Authorization"] = "Bearer helm_nope"
    assert (await plain.get(f"/api/keyword-queue/{project.slug}")).status_code == 401
    plain.headers["Authorization"] = f"Bearer {token}"
    assert (await plain.get("/api/keyword-queue/missing")).status_code == 404
    demo = await make_project(demo=True)
    assert (await plain.get(f"/api/keyword-queue/{demo.slug}")).status_code == 404


async def test_indexing_overview_rows_for_the_cards(auth_client):
    project = await make_project(name="Overview Site")
    await seed_site(project)
    await seed_candidates(project)
    rows = (await auth_client.get("/api/indexing/overview")).json()
    row = next(r for r in rows if r["slug"] == project.slug)
    assert row["total_urls"] == 3 and row["indexed_percent"] == 50.0 and row["thin"] == 1
    assert row["crawled_not_indexed"] == 0 and row["pending_keywords"] == 2
