import functools
import inspect
import json
from contextlib import asynccontextmanager
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from app.core import mcp_tokens
from app.core.config import settings
from app.db.session import async_session_maker
from app.mcp_server import server as mcp_server
from app.models.indexing import (
    AppSetting,
    InspectRequest,
    KeywordCandidate,
    KeywordRun,
    McpCall,
    McpToken,
    PageSignal,
    SitemapUrl,
    UrlInspection,
)
from app.models.project import Project, TrafficDaily

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest_asyncio.fixture(autouse=True)
async def isolated(monkeypatch):
    monkeypatch.setattr(settings, "mcp_allowed_hosts", ["testserver"])
    mcp_server.limiter._hits.clear()
    async with async_session_maker() as db:
        await db.execute(update(Project).values(is_pipeline=False))
        for model in (AppSetting, KeywordCandidate, KeywordRun, SitemapUrl, UrlInspection, PageSignal, InspectRequest, McpToken, McpCall):
            await db.execute(delete(model))
        await db.commit()


@asynccontextmanager
async def open_client(host="testserver"):
    app = mcp_server.build_app()
    inner = app.app
    async with inner.router.lifespan_context(inner):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{host}") as client:
            yield client


def with_client(fn):
    """The MCP session manager's task group must be entered and exited in one task, which a pytest fixture cannot do."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        async with open_client() as client:
            return await fn(client, *args, **kwargs)

    params = list(inspect.signature(fn).parameters.values())[1:]
    wrapper.__signature__ = inspect.Signature(params)
    return wrapper


async def token(scope="read", label="t") -> str:
    async with async_session_maker() as db:
        return (await mcp_tokens.create_token(db, label, scope))[1]


async def rpc(client, method, params=None, bearer=None, rid=1):
    headers = {**HEADERS, **({"Authorization": f"Bearer {bearer}"} if bearer else {})}
    response = await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    return response


async def call_tool(client, bearer, name, **arguments):
    response = await rpc(client, "tools/call", {"name": name, "arguments": arguments}, bearer)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def payload(result) -> dict:
    return json.loads(result["content"][0]["text"])


async def make_project(demo=False) -> Project:
    async with async_session_maker() as db:
        project = Project(slug=f"mcp-{uuid.uuid4().hex[:8]}", name="Mcp Site", category="seo-content-site", url="https://mcp.example/", is_pipeline=True, gsc_site_url="https://mcp.example/", is_demo=demo)
        db.add(project)
        await db.commit()
        return project


async def calls() -> list[McpCall]:
    async with async_session_maker() as db:
        return list((await db.execute(select(McpCall).order_by(McpCall.created_at))).scalars())


# ---------------------------------------------------------------- auth and transport


@with_client
async def test_requests_without_a_valid_token_are_rejected_before_any_tool_runs(mcp_client):
    assert (await rpc(mcp_client, "tools/list")).status_code == 401
    assert (await rpc(mcp_client, "tools/list", bearer="helm_wrong")).status_code == 401
    assert (await rpc(mcp_client, "tools/list", bearer=settings.sync_token)).status_code == 401  # the sync token is never accepted here
    revoked = await token()
    async with async_session_maker() as db:
        await db.execute(update(McpToken).values(revoked_at=datetime.now(timezone.utc)))
        await db.commit()
    assert (await rpc(mcp_client, "tools/list", bearer=revoked)).status_code == 401
    assert (await mcp_client.get("/health")).json() == {"status": "ok"}
    assert await calls() == []


async def test_unknown_host_header_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "mcp_allowed_hosts", ["mcp.billtoolbox.com"])
    other = mcp_server.build_app()
    inner = other.app
    async with inner.router.lifespan_context(inner):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=other), base_url="http://evil.example") as client:
            response = await rpc(client, "tools/list", bearer=await token())
    assert response.status_code in (400, 403, 421)


@with_client
async def test_tools_list_has_the_planned_tools(mcp_client):
    response = await rpc(mcp_client, "tools/list", bearer=await token())
    names = {t["name"] for t in response.json()["result"]["tools"]}
    assert {"list_projects", "get_traffic", "get_indexing_summary", "list_urls", "get_url_history", "list_keyword_candidates", "get_sitemap_status",
            "inspect_url", "run_keyword_generator", "set_candidate_status", "export_keyword_queue"} <= names


# ---------------------------------------------------------------- read tools


@with_client
async def test_read_tools_return_data_and_are_logged(mcp_client):
    project = await make_project()
    demo = await make_project(demo=True)
    async with async_session_maker() as db:
        for path in ("a", "b"):
            db.add(SitemapUrl(project_id=project.id, url=f"https://mcp.example/{path}"))
        db.add(PageSignal(project_id=project.id, url="https://mcp.example/a", http_status=200, word_count=50, title="A"))
        today = date.today()
        for i in range(3):
            db.add(TrafficDaily(project_id=project.id, metric_date=today - timedelta(days=i + 3), clicks=10, impressions=100, sessions=5))
        db.add(KeywordCandidate(project_id=project.id, keyword="kw one", score=42.0))
        await db.commit()
    bearer = await token(label="reader")

    listed = payload(await call_tool(mcp_client, bearer, "list_projects"))
    slugs = [p["slug"] for p in listed["result"]] if "result" in listed else [p["slug"] for p in listed["projects"]]
    assert project.slug in slugs and demo.slug not in slugs  # demo projects are never exposed

    traffic = payload(await call_tool(mcp_client, bearer, "get_traffic", project=project.slug, days=7))
    assert traffic["totals"] == {"clicks": 30, "impressions": 300, "sessions": 15}

    summary = payload(await call_tool(mcp_client, bearer, "get_indexing_summary", project=project.slug))
    assert summary["total_urls"] == 2 and summary["counts"]["thin"] == 1 and summary["counts"]["unknown"] == 1

    urls = payload(await call_tool(mcp_client, bearer, "list_urls", project=project.slug, issue="thin", limit=5))
    assert urls["total"] == 1 and urls["urls"][0]["url"].endswith("/a")

    history = payload(await call_tool(mcp_client, bearer, "get_url_history", project=project.slug, url="https://mcp.example/a"))
    assert history["signals"][0]["word_count"] == 50

    keywords = payload(await call_tool(mcp_client, bearer, "list_keyword_candidates", project=project.slug))
    assert keywords["candidates"][0]["keyword"] == "kw one"
    assert "sitemaps" in payload(await call_tool(mcp_client, bearer, "get_sitemap_status", project=project.slug))

    logged = await calls()
    assert {c.tool for c in logged} >= {"list_projects", "get_traffic", "list_urls"} and {c.status for c in logged} == {"ok"}
    assert {c.token_label for c in logged} == {"reader"} and all(len(c.args_hash) == 64 for c in logged)


@with_client
async def test_tool_errors_are_clean_and_logged(mcp_client):
    bearer = await token()
    result = await call_tool(mcp_client, bearer, "get_indexing_summary", project="nope")
    assert result["isError"] and "No project with slug" in result["content"][0]["text"]
    project = await make_project()
    bad_issue = await call_tool(mcp_client, bearer, "list_urls", project=project.slug, issue="bogus")
    assert bad_issue["isError"] and "issue must be one of" in bad_issue["content"][0]["text"]
    bad_days = await call_tool(mcp_client, bearer, "get_traffic", project=project.slug, days=9999)
    assert bad_days["isError"]
    assert {c.status for c in await calls()} == {"error"}


@with_client
async def test_demo_project_is_invisible_to_tools(mcp_client):
    demo = await make_project(demo=True)
    result = await call_tool(mcp_client, await token(), "get_indexing_summary", project=demo.slug)
    assert result["isError"]


# ---------------------------------------------------------------- write tools and scope


@with_client
async def test_read_scope_cannot_use_write_tools_and_denials_are_logged(mcp_client):
    project = await make_project()
    bearer = await token("read")
    for name, args in (
        ("inspect_url", {"project": project.slug, "url": "https://mcp.example/a"}),
        ("run_keyword_generator", {"project": project.slug}),
        ("set_candidate_status", {"candidate_id": str(uuid.uuid4()), "status": "accepted"}),
        ("export_keyword_queue", {"project": project.slug}),
    ):
        result = await call_tool(mcp_client, bearer, name, **args)
        assert result["isError"] and "read-only" in result["content"][0]["text"]
    assert [c.status for c in await calls()] == ["denied"] * 4
    async with async_session_maker() as db:
        assert (await db.execute(select(func.count()).select_from(InspectRequest))).scalar_one() == 0


@with_client
async def test_write_tools_inspect_and_decide_and_export(mcp_client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "keyword_export_dir", str(tmp_path))
    project = await make_project()
    async with async_session_maker() as db:
        db.add(SitemapUrl(project_id=project.id, url="https://mcp.example/a"))
        candidate = KeywordCandidate(project_id=project.id, keyword="export me", score=9.0)
        db.add(candidate)
        await db.commit()
    bearer = await token("write", label="writer")

    queued = payload(await call_tool(mcp_client, bearer, "inspect_url", project=project.slug, url="https://mcp.example/a"))
    assert queued["queued"] is True and queued["budget"]["remaining"] == 499
    again = await call_tool(mcp_client, bearer, "inspect_url", project=project.slug, url="https://mcp.example/a")
    assert again["isError"] and "already queued" in again["content"][0]["text"]
    unknown = await call_tool(mcp_client, bearer, "inspect_url", project=project.slug, url="https://other.example/")
    assert unknown["isError"]
    async with async_session_maker() as db:
        request = (await db.execute(select(InspectRequest))).scalar_one()
        assert request.requested_by == "mcp:writer"

    decided = payload(await call_tool(mcp_client, bearer, "set_candidate_status", candidate_id=str(candidate.id), status="accepted"))
    assert decided["status"] == "accepted"
    assert (await call_tool(mcp_client, bearer, "set_candidate_status", candidate_id="not-a-uuid", status="accepted"))["isError"]
    assert (await call_tool(mcp_client, bearer, "set_candidate_status", candidate_id=str(candidate.id), status="written"))["isError"]

    exported = payload(await call_tool(mcp_client, bearer, "export_keyword_queue", project=project.slug))
    assert exported["exported"] == 1 and exported["file_written"] is True
    assert json.loads((tmp_path / project.slug / "keyword_queue.json").read_text())["keywords"][0]["keyword"] == "export me"
    locked = await call_tool(mcp_client, bearer, "set_candidate_status", candidate_id=str(candidate.id), status="rejected")
    assert locked["isError"] and "already exported" in locked["content"][0]["text"]


@with_client
async def test_run_keyword_generator_tool_refuses_when_a_run_is_going(mcp_client, monkeypatch):
    from app.keywords import generator

    started = []

    async def fake_execute(session_factory, run_id, **kwargs):
        started.append(run_id)

    monkeypatch.setattr(generator, "execute_run", fake_execute)
    project = await make_project()
    bearer = await token("write")
    first = payload(await call_tool(mcp_client, bearer, "run_keyword_generator", project=project.slug))
    assert first["status"] == "running"
    second = await call_tool(mcp_client, bearer, "run_keyword_generator", project=project.slug)
    assert second["isError"] and "already in progress" in second["content"][0]["text"]
    status = payload(await call_tool(mcp_client, bearer, "get_keyword_run_status", project=project.slug))
    assert status["result"][0]["status"] == "running"
    from app.keywords import launch

    for task in list(launch.running):
        await task
    assert len(started) == 1


# ---------------------------------------------------------------- rate limit


@with_client
async def test_rate_limit_applies_per_token_and_is_logged(mcp_client):
    limited, other = await token(label="busy"), await token(label="quiet")
    mcp_server.limiter.per_minute = 3
    try:
        results = [await call_tool(mcp_client, limited, "list_projects") for _ in range(4)]
        assert [bool(r.get("isError")) for r in results] == [False, False, False, True]
        assert "Rate limit" in results[3]["content"][0]["text"]
        assert not (await call_tool(mcp_client, other, "list_projects")).get("isError")
    finally:
        mcp_server.limiter.per_minute = mcp_tokens.RATE_LIMIT_PER_MINUTE
    assert [c.status for c in await calls() if c.token_label == "busy"] == ["ok", "ok", "ok", "rate_limited"]
