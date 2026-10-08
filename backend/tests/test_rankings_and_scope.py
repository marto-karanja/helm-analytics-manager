import uuid
from datetime import date, datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import delete, select

from app.core import mcp_tokens
from app.core import scope as scope_vars
from app.db.session import async_session_maker
from app.indexing import manual, rankings
from app.keywords import rollup
from app.mcp_server import service as svc
from app.models.alerts import AlertEvent
from app.models.indexing import GscQueryRollup, McpCall, McpToken, RollupRequest, SitemapUrl
from app.models.project import Project
from tests.fakes import FakeResponse, FakeSession

W0 = date(2026, 9, 14)  # Mondays
W1 = date(2026, 9, 21)
W2 = date(2026, 9, 28)


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    yield
    async with async_session_maker() as db:
        await db.execute(delete(Project).where(Project.slug.like("rk-%")))
        await db.execute(delete(McpToken).where(McpToken.label.like("rk-%")))
        await db.commit()


async def make_project(gsc="https://rk.example/") -> Project:
    async with async_session_maker() as db:
        p = Project(slug=f"rk-{uuid.uuid4().hex[:8]}", name="rk", category="seo-content-site", url="https://rk.example/", is_pipeline=True, gsc_site_url=gsc)
        db.add(p)
        await db.commit()
        return p


async def add_rows(project, rows):
    async with async_session_maker() as db:
        for week, query, page, clicks, impressions, position in rows:
            db.add(GscQueryRollup(project_id=project.id, week_start=week, query=query, page=page, clicks=clicks, impressions=impressions, position_avg=position))
        await db.commit()


async def token(label="rk-t", scope="read", slugs=None) -> str:
    async with async_session_maker() as db:
        _, raw = await mcp_tokens.create_token(db, label, scope, slugs)
    return raw


def bearer(raw):
    return {"authorization": f"Bearer {raw}"}


# ---------------------------------------------------------------- pure ranking maths


def row(page, query, clicks, impressions, position):
    return {"page": page, "query": query, "clicks": clicks, "impressions": impressions, "position_avg": position}


def test_position_is_impression_weighted_not_a_plain_mean():
    current = [row("https://x/a", "big", 5, 900, 4.0), row("https://x/a", "tiny", 0, 100, 40.0)]
    (page,) = rankings.build_rankings(current, [], {})["pages"]
    assert page["position"] == 7.6  # (4*900 + 40*100) / 1000, not (4+40)/2


def test_position_change_is_positive_when_the_page_moved_up():
    current = [row("https://x/a", "q", 1, 100, 6.0)]
    prior = [row("https://x/a/", "q", 1, 100, 9.0)]  # trailing slash must not break the join
    (page,) = rankings.build_rankings(current, prior, {})["pages"]
    assert page["position_prior"] == 9.0 and page["position_change"] == 3.0
    (worse,) = rankings.build_rankings(prior, current, {})["pages"]
    assert worse["position_change"] == -3.0


def test_new_page_has_no_prior_position():
    (page,) = rankings.build_rankings([row("https://x/new", "q", 0, 50, 12.0)], [], {})["pages"]
    assert page["position_prior"] is None and page["position_change"] is None


def test_min_impressions_filters_noise_but_not_a_page_asked_for_by_url():
    current = [row("https://x/a", "q", 0, 3, 30.0), row("https://x/b", "q", 1, 200, 5.0)]
    assert [p["url"] for p in rankings.build_rankings(current, [], {}, min_impressions=10)["pages"]] == ["https://x/b"]
    assert [p["url"] for p in rankings.build_rankings(current, [], {}, min_impressions=10, only_url="https://www.x/a/?utm=1")["pages"]] == ["https://x/a"]


def test_top_queries_are_merged_across_weeks_and_capped():
    current = [row("https://x/a", f"q{i}", 0, 10 + i, 8.0) for i in range(6)] + [row("https://x/a", "q5", 1, 10, 6.0)]
    (page,) = rankings.build_rankings(current, [], {})["pages"]
    assert page["query_count"] == 6 and len(page["top_queries"]) == 3
    assert page["top_queries"][0]["query"] == "q5" and page["top_queries"][0]["impressions"] == 25


def test_indexing_state_is_joined_on_the_normalised_url():
    state = {rankings.normalise_url("https://www.x/a/"): {"issue": "crawled_not_indexed", "coverage_state": "Crawled - currently not indexed"}}
    (page,) = rankings.build_rankings([row("https://x/a", "q", 0, 50, 15.0)], [], state)["pages"]
    assert page["indexing"] == "crawled_not_indexed"


# ---------------------------------------------------------------- over the database


async def test_page_rankings_use_equal_consecutive_windows_and_report_freshness():
    p = await make_project()
    await add_rows(p, [(W0, "q", "https://rk.example/a", 1, 100, 10.0), (W1, "q", "https://rk.example/a", 2, 100, 8.0), (W2, "q", "https://rk.example/a", 3, 100, 6.0)])
    async with async_session_maker() as db:
        out = await rankings.page_rankings(db, p, weeks=1, min_impressions=0)
    assert out["window"]["latest_week_start"] == W2
    (page,) = out["pages"]
    assert page["position"] == 6.0 and page["position_prior"] == 8.0 and page["position_change"] == 2.0
    assert out["refresh_pending"] is False and "last_refreshed_at" in out


async def test_no_rollup_data_says_how_to_get_some():
    p = await make_project()
    async with async_session_maker() as db:
        out = await rankings.page_rankings(db, p)
    assert out["pages"] == [] and "refresh" in out["note"].lower()


# ---------------------------------------------------------------- token scoping, REST


async def test_a_scoped_token_sees_only_its_own_project_over_rest(client):
    mine, other = await make_project(), await make_project()
    await add_rows(mine, [(W2, "q", "https://rk.example/a", 1, 50, 5.0)])
    raw = await token(slugs=[mine.slug])

    listed = (await client.get("/api/v1/projects", headers=bearer(raw))).json()["projects"]
    assert [x["slug"] for x in listed] == [mine.slug]
    ok = await client.get(f"/api/v1/projects/{mine.slug}/rankings?min_impressions=0", headers=bearer(raw))
    assert ok.status_code == 200 and ok.json()["pages"][0]["url"] == "https://rk.example/a"

    denied = await client.get(f"/api/v1/projects/{other.slug}/rankings", headers=bearer(raw))
    missing = await client.get("/api/v1/projects/rk-does-not-exist/rankings", headers=bearer(raw))
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["detail"].replace(other.slug, "X") == missing.json()["detail"].replace("rk-does-not-exist", "X")  # no existence leak


async def test_unscoped_token_sees_every_project(client):
    a, b = await make_project(), await make_project()
    raw = await token()
    slugs = {x["slug"] for x in (await client.get("/api/v1/projects", headers=bearer(raw))).json()["projects"]}
    assert {a.slug, b.slug} <= slugs


async def test_bad_or_missing_token_is_401(client):
    p = await make_project()
    assert (await client.get(f"/api/v1/projects/{p.slug}/alerts")).status_code == 401
    assert (await client.get(f"/api/v1/projects/{p.slug}/alerts", headers=bearer("helm_nope"))).status_code == 401
    raw = await token()
    async with async_session_maker() as db:
        row_ = (await db.execute(select(McpToken).where(McpToken.token_hash == mcp_tokens.hash_token(raw)))).scalar_one()
        from datetime import datetime, timezone

        row_.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    assert (await client.get(f"/api/v1/projects/{p.slug}/alerts", headers=bearer(raw))).status_code == 401


async def test_scoped_token_cannot_reach_other_projects_candidates_or_queue(client):
    mine, other = await make_project(), await make_project()
    raw = await token(slugs=[mine.slug])
    assert (await client.get(f"/api/v1/projects/{other.slug}/keyword-queue", headers=bearer(raw))).status_code == 404
    assert (await client.get(f"/api/keyword-queue/{other.slug}", headers=bearer(raw))).status_code == 404
    assert (await client.get(f"/api/keyword-queue/{mine.slug}", headers=bearer(raw))).status_code == 200


async def test_alerts_endpoint_returns_events(client):
    p = await make_project()
    async with async_session_maker() as db:
        db.add(AlertEvent(project_id=p.id, kind="zero_impressions", severity="red", state="open", message="Zero impressions"))
        db.add(AlertEvent(project_id=p.id, kind="no_data", severity="yellow", state="resolved", message="No data"))
        await db.commit()
    raw = await token()
    open_ = (await client.get(f"/api/v1/projects/{p.slug}/alerts", headers=bearer(raw))).json()["alerts"]
    assert [a["kind"] for a in open_] == ["zero_impressions"]
    assert len((await client.get(f"/api/v1/projects/{p.slug}/alerts?state=all", headers=bearer(raw))).json()["alerts"]) == 2
    assert (await client.get(f"/api/v1/projects/{p.slug}/alerts?state=bogus", headers=bearer(raw))).status_code == 400


async def test_calls_are_audited_without_the_token(client):
    p = await make_project()
    raw = await token(label="rk-audit")
    await client.get(f"/api/v1/projects/{p.slug}/alerts", headers=bearer(raw))
    async with async_session_maker() as db:
        calls = list((await db.execute(select(McpCall).where(McpCall.token_label == "rk-audit"))).scalars())
    assert [c.tool for c in calls] == ["rest:alerts"] and calls[0].status == "ok"
    assert raw not in repr([(c.tool, c.args_hash, c.token_label) for c in calls])


async def test_rest_rate_limit(client, monkeypatch):
    from app.api import v1

    monkeypatch.setattr(v1, "limiter", mcp_tokens.RateLimiter(per_minute=2))
    raw = await token()
    codes = [(await client.get("/api/v1/projects", headers=bearer(raw))).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ---------------------------------------------------------------- token scoping, MCP service layer


async def test_service_layer_enforces_scope_for_every_lookup():
    mine, other = await make_project(), await make_project()
    reset = scope_vars.allowed_slugs.set(frozenset({mine.slug}))
    try:
        async with async_session_maker() as db:
            assert [x["slug"] for x in await svc.list_projects(db)] == [mine.slug]
            assert (await svc.get_alerts(db, mine.slug, "open"))["project"] == mine.slug
            for call in (svc.get_alerts(db, other.slug, "open"), svc.get_page_rankings(db, other.slug, 4, 10, 100, None), svc.refresh_rankings(db, other.slug, "t")):
                try:
                    await call
                    raise AssertionError("out-of-scope project was served")
                except svc.McpToolError as exc:
                    assert "No project with slug" in str(exc)
    finally:
        scope_vars.allowed_slugs.reset(reset)


# ---------------------------------------------------------------- token creation


async def test_token_creation_validates_project_slugs(auth_client):
    p = await make_project()
    ok = await auth_client.post("/api/mcp-tokens", json={"label": "rk-new", "scope": "read", "project_slugs": [p.slug]})
    assert ok.status_code == 201 and ok.json()["project_slugs"] == [p.slug]
    unknown = await auth_client.post("/api/mcp-tokens", json={"label": "rk-bad", "project_slugs": ["nope-nope"]})
    empty = await auth_client.post("/api/mcp-tokens", json={"label": "rk-empty", "project_slugs": []})
    assert unknown.status_code == empty.status_code == 422
    plain = await auth_client.post("/api/mcp-tokens", json={"label": "rk-all"})
    assert plain.json()["project_slugs"] is None


# ---------------------------------------------------------------- manual refresh


async def test_manual_refresh_needs_write_scope_and_is_rate_limited(client):
    p = await make_project()
    read, write = await token("rk-r", "read"), await token("rk-w", "write", [p.slug])
    assert (await client.post(f"/api/v1/projects/{p.slug}/rankings/refresh", headers=bearer(read))).status_code == 403
    first = await client.post(f"/api/v1/projects/{p.slug}/rankings/refresh", headers=bearer(write))
    assert first.status_code == 202 and first.json()["queued"] is True
    again = await client.post(f"/api/v1/projects/{p.slug}/rankings/refresh", headers=bearer(write))
    assert again.status_code == 409 and "already queued" in again.json()["detail"]
    async with async_session_maker() as db:
        pending = list((await db.execute(select(RollupRequest).where(RollupRequest.project_id == p.id))).scalars())
    assert len(pending) == 1 and pending[0].requested_by == "rest:rk-w"
    state = (await client.get(f"/api/v1/projects/{p.slug}/rankings", headers=bearer(write))).json()
    assert state["refresh_pending"] is True


async def test_refresh_throttle_after_completion_and_missing_property():
    p = await make_project()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    async with async_session_maker() as db:
        await manual.queue_rollup(db, p, "t", now=now)
        row_ = (await db.execute(select(RollupRequest).where(RollupRequest.project_id == p.id))).scalar_one()
        row_.done_at = now
        row_.requested_at = now
        await db.commit()
        try:
            await manual.queue_rollup(db, p, "t", now=now + timedelta(minutes=10))
            raise AssertionError("throttle did not apply")
        except manual.QueueError as exc:
            assert exc.status_code == 429
        assert (await manual.queue_rollup(db, p, "t", now=now + timedelta(minutes=31)))["queued"] is True
    bare = await make_project(gsc=None)
    async with async_session_maker() as db:
        try:
            await manual.queue_rollup(db, bare, "t")
            raise AssertionError("no property should be refused")
        except manual.QueueError as exc:
            assert exc.status_code == 409


async def test_collector_runs_a_queued_refresh_once_per_project_and_closes_requests():
    p = await make_project()
    async with async_session_maker() as db:
        db.add_all([RollupRequest(project_id=p.id, requested_by="a"), RollupRequest(project_id=p.id, requested_by="b")])
        await db.commit()

    def respond(url, body):
        return FakeResponse({"rows": [{"keys": ["best thing", "https://rk.example/a", "2026-09-29"], "clicks": 2, "impressions": 40, "ctr": 0.05, "position": 7.0}]})

    session = FakeSession(respond)
    today = date(2026, 10, 8)
    closed = await rollup.run_rollup_requests(async_session_maker, session, today=today, now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert closed == 2 and len(session.calls) == 1  # one Search Console pull for two requests
    async with async_session_maker() as db:
        reqs = list((await db.execute(select(RollupRequest).where(RollupRequest.project_id == p.id))).scalars())
        data = list((await db.execute(select(GscQueryRollup).where(GscQueryRollup.project_id == p.id))).scalars())
    assert all(r.done_at is not None and r.error is None for r in reqs) and len(data) == 1
    async with async_session_maker() as db:
        out = await rankings.page_rankings(db, p, weeks=1, min_impressions=0)
    assert out["refresh_pending"] is False and out["last_manual_refresh_at"] is not None
    assert out["pages"][0]["position"] == 7.0


async def test_failed_refresh_is_recorded_on_the_request():
    p = await make_project()
    async with async_session_maker() as db:
        db.add(RollupRequest(project_id=p.id, requested_by="a"))
        await db.commit()
    await rollup.run_rollup_requests(async_session_maker, FakeSession(lambda u, b: FakeResponse(status_code=403)), today=date(2026, 10, 8))
    async with async_session_maker() as db:
        (req,) = (await db.execute(select(RollupRequest).where(RollupRequest.project_id == p.id))).scalars()
    assert req.done_at is not None and req.error


# ---------------------------------------------------------------- MCP tools


async def test_new_mcp_tools_enforce_project_scope_and_write_scope():
    from mcp.server.mcpserver.exceptions import ToolError

    from app.mcp_server import server

    mine, other = await make_project(), await make_project()
    await add_rows(mine, [(W2, "q", "https://rk.example/a", 1, 50, 5.0)])
    names = {t.name for t in await server.mcp.list_tools()}
    assert {"get_page_rankings", "get_alerts", "refresh_rankings"} <= names

    caller = server.Caller(token_id=str(uuid.uuid4()), label="rk-mcp", scope="read", projects=frozenset({mine.slug}))
    reset = server.current_caller.set(caller)
    try:
        out = await server.get_page_rankings(mine.slug, min_impressions=0)
        assert out["pages"][0]["url"] == "https://rk.example/a"
        for call in (server.get_page_rankings(other.slug), server.get_alerts(other.slug)):
            try:
                await call
                raise AssertionError("out-of-scope project was served")
            except ToolError as exc:
                assert "No project with slug" in str(exc)
        try:
            await server.refresh_rankings(mine.slug)
            raise AssertionError("read token queued a refresh")
        except ToolError as exc:
            assert "read-only" in str(exc)
    finally:
        server.current_caller.reset(reset)

    writer = server.Caller(token_id=str(uuid.uuid4()), label="rk-mcp-w", scope="write", projects=frozenset({mine.slug}))
    reset = server.current_caller.set(writer)
    try:
        assert (await server.refresh_rankings(mine.slug))["queued"] is True
    finally:
        server.current_caller.reset(reset)
    assert scope_vars.allowed_slugs.get() is None  # the scope never leaks past the call


async def test_owner_ui_endpoints_for_rankings_and_manual_refresh(auth_client, client):
    p = await make_project()
    await add_rows(p, [(W2, "q", "https://rk.example/a", 1, 50, 5.0)])
    # the auth_client user is not the owner of a project row; projects are global, so look it up by id
    got = await auth_client.get(f"/api/projects/{p.id}/rankings?min_impressions=0")
    assert got.status_code == 200 and got.json()["pages"][0]["position"] == 5.0
    queued = await auth_client.post(f"/api/projects/{p.id}/rankings/refresh")
    assert queued.status_code == 202
    assert (await auth_client.post(f"/api/projects/{p.id}/rankings/refresh")).status_code == 409
    assert (await auth_client.get(f"/api/projects/{p.id}/rankings")).json()["refresh_pending"] is True
    demo = await client.post("/api/auth/demo-login")
    demo_h = {"authorization": f"Bearer {demo.json()['access_token']}"}
    assert (await client.post(f"/api/projects/{p.id}/rankings/refresh", headers=demo_h)).status_code in (403, 404)
