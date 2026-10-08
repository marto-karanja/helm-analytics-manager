"""Token-authenticated read API for the owner's other projects and pipelines: /api/v1/...

Same bearer tokens, per-project scoping, rate limit and audit log as the MCP server, and the same service
functions underneath, so the two front ends cannot disagree. Read endpoints need any token; the refresh
endpoint needs a write-scope token."""
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.core import mcp_tokens
from app.core import scope as scope_vars
from app.db.session import async_session_maker
from app.indexing import manual
from app.keywords import export as export_mod
from app.mcp_server import service as svc
from app.models.indexing import McpCall, McpToken

logger = logging.getLogger("helm.api.v1")
router = APIRouter(prefix="/v1", tags=["v1 (tokens)"])
limiter = mcp_tokens.RateLimiter()
caller_label: ContextVar[str] = ContextVar("helm_rest_label", default="unknown")


async def _authenticate(authorization: str | None) -> McpToken:
    scheme, _, raw = (authorization or "").partition(" ")
    async with async_session_maker() as db:
        token = await mcp_tokens.verify_token(db, raw) if scheme.lower() == "bearer" else None
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return token


async def _audit(token: McpToken, tool: str, args: dict, outcome: str) -> None:
    digest = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
    try:
        async with async_session_maker() as db:
            db.add(McpCall(token_label=token.label, tool=f"rest:{tool}", args_hash=digest, status=outcome))
            await db.commit()
    except Exception:  # noqa: BLE001 -- failing to audit must not break or leak into the response
        logger.exception("could not record REST call")


def _http_error(exc: svc.McpToolError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if str(exc).startswith("No project with slug") or str(exc) == "No such candidate." else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(exc))


async def _call(authorization: str | None, tool: str, args: dict, work: Callable[[Any], Awaitable[Any]], write: bool = False) -> Any:
    token = await _authenticate(authorization)
    outcome = "ok"
    reset = scope_vars.allowed_slugs.set(scope_vars.as_scope(token.project_slugs))
    label_reset = caller_label.set(token.label)
    try:
        if write and not mcp_tokens.allows(token, "write"):
            outcome = "denied"
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This token is read-only. Create a write-scope token in Helm settings.")
        if not limiter.allow(str(token.id)):
            outcome = "rate_limited"
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Rate limit exceeded ({limiter.per_minute} calls per minute)")
        async with async_session_maker() as db:
            return await work(db)
    except svc.McpToolError as exc:
        outcome = "error"
        raise _http_error(exc) from exc
    except manual.QueueError as exc:
        outcome = "error"
        raise HTTPException(exc.status_code, exc.detail) from exc
    finally:
        scope_vars.allowed_slugs.reset(reset)
        caller_label.reset(label_reset)
        await _audit(token, tool, args, outcome)


@router.get("/projects")
async def projects(authorization: str | None = Header(None)) -> dict:
    """Projects this token can see, with the slug every other endpoint takes."""
    return {"projects": await _call(authorization, "projects", {}, lambda db: svc.list_projects(db))}


@router.get("/projects/{slug}/traffic")
async def traffic(slug: str, days: int = Query(28, ge=1, le=svc.MAX_TRAFFIC_DAYS), authorization: str | None = Header(None)) -> dict:
    """Search Console and GA4 totals plus daily rows for the last `days` days of collected data."""
    return await _call(authorization, "traffic", {"slug": slug, "days": days}, lambda db: svc.get_traffic(db, slug, days))


@router.get("/projects/{slug}/indexing")
async def indexing(slug: str, authorization: str | None = Header(None)) -> dict:
    """Counts of URLs per indexing issue and the indexed percentage."""
    return await _call(authorization, "indexing", {"slug": slug}, lambda db: svc.get_indexing_summary(db, slug))


@router.get("/projects/{slug}/urls")
async def urls(slug: str, issue: str | None = None, limit: int = Query(50, ge=1, le=svc.MAX_LIST), authorization: str | None = Header(None)) -> dict:
    """Sitemap URLs with their indexing issue; filter by `issue`."""
    return await _call(authorization, "urls", {"slug": slug, "issue": issue, "limit": limit}, lambda db: svc.list_urls(db, slug, issue, limit))


@router.get("/projects/{slug}/urls/history")
async def url_history(slug: str, url: str, authorization: str | None = Header(None)) -> dict:
    """Inspection and page-signal history for one URL in the project's sitemap."""
    return await _call(authorization, "url_history", {"slug": slug, "url": url}, lambda db: svc.get_url_history(db, slug, url))


@router.get("/projects/{slug}/rankings")
async def rankings(
    slug: str,
    weeks: int = Query(4, ge=1, le=12),
    min_impressions: int = Query(10, ge=0),
    limit: int = Query(100, ge=1, le=500),
    url: str | None = None,
    authorization: str | None = Header(None),
) -> dict:
    """Where each page ranks: impression-weighted average position over the last `weeks` weeks, the change against
    the previous window (positive = moved up), clicks, impressions, top queries and indexing state. Pass `url` for
    every query one page ranks for."""
    args = {"slug": slug, "weeks": weeks, "min_impressions": min_impressions, "limit": limit, "url": url}
    return await _call(authorization, "rankings", args, lambda db: svc.get_page_rankings(db, slug, weeks, min_impressions, limit, url))


@router.post("/projects/{slug}/rankings/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_rankings(slug: str, authorization: str | None = Header(None)) -> dict:
    """Queue an on-demand refresh instead of waiting for the weekly run (write-scope token; one per project per 30
    minutes). Poll /rankings and watch `last_refreshed_at`."""

    async def work(db):
        project = await svc.find_project(db, slug)
        return await manual.queue_rollup(db, project, f"rest:{caller_label.get()}")

    return await _call(authorization, "refresh_rankings", {"slug": slug}, work, write=True)


@router.get("/projects/{slug}/keywords")
async def keywords(slug: str, status_filter: str | None = Query(None, alias="status"), authorization: str | None = Header(None)) -> dict:
    """Keyword candidates ranked by score; status is proposed, accepted, rejected or written."""
    return await _call(authorization, "keywords", {"slug": slug, "status": status_filter}, lambda db: svc.list_keyword_candidates(db, slug, status_filter))


@router.get("/projects/{slug}/keyword-queue")
async def keyword_queue(slug: str, authorization: str | None = Header(None)) -> dict:
    """The accepted keywords waiting to be written, in the format publishing pipelines consume."""

    async def work(db):
        project = await svc.find_project(db, slug)
        return export_mod.queue_payload(project, await export_mod.queue_rows(db, project.id))

    return await _call(authorization, "keyword_queue", {"slug": slug}, work)


@router.get("/projects/{slug}/keyword-runs")
async def keyword_runs(slug: str, authorization: str | None = Header(None)) -> dict:
    """The five most recent keyword generator runs."""
    return {"runs": await _call(authorization, "keyword_runs", {"slug": slug}, lambda db: svc.recent_runs(db, slug))}


@router.get("/projects/{slug}/sitemaps")
async def sitemaps(slug: str, authorization: str | None = Header(None)) -> dict:
    """Search Console's view of each submitted sitemap."""
    return await _call(authorization, "sitemaps", {"slug": slug}, lambda db: svc.get_sitemap_status(db, slug))


@router.get("/projects/{slug}/alerts")
async def alerts(slug: str, state: str = "open", authorization: str | None = Header(None)) -> dict:
    """Alerts for the project: state is open, resolved or all."""
    return await _call(authorization, "alerts", {"slug": slug, "state": state}, lambda db: svc.get_alerts(db, slug, state))
