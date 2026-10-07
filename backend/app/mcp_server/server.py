"""Helm MCP server: streamable HTTP under /mcp, bearer-token auth, read/write scopes, per-token rate limit,
and a log row for every call. It runs as its own compose service and calls the service layer directly."""
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core import mcp_tokens
from app.core.config import settings
from app.db.session import async_session_maker
from app.mcp_server import service as svc
from app.models.indexing import McpCall

logger = logging.getLogger("helm.mcp")

INSTRUCTIONS = (
    "Helm tracks search traffic, indexing status and keyword candidates for the owner's websites. "
    "Call list_projects first for valid project slugs. Read tools are free; inspect_url spends the daily "
    "Search Console inspection budget, and run_keyword_generator spends the daily LLM budget."
)


@dataclass(frozen=True)
class Caller:
    token_id: str
    label: str
    scope: str


current_caller: ContextVar[Caller | None] = ContextVar("helm_mcp_caller", default=None)
limiter = mcp_tokens.RateLimiter()

mcp = MCPServer("helm", instructions=INSTRUCTIONS)


async def _log(caller: Caller, tool: str, args: dict, status: str) -> None:
    digest = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
    try:
        async with async_session_maker() as db:
            db.add(McpCall(token_label=caller.label, tool=tool, args_hash=digest, status=status))
            await db.commit()
    except Exception:  # noqa: BLE001 -- failing to log must not break or leak into the tool result
        logger.exception("could not record MCP call")


async def _call(tool: str, scope: str, args: dict, work: Callable[..., Awaitable]) -> dict:
    caller = current_caller.get()
    if caller is None:
        raise ToolError("Not authenticated.")
    status = "ok"
    try:
        if scope == "write" and caller.scope != "write":
            status = "denied"
            raise ToolError("This token is read-only. Create a write-scope token in Helm settings to use this tool.")
        if not limiter.allow(caller.token_id):
            status = "rate_limited"
            raise ToolError(f"Rate limit exceeded ({limiter.per_minute} calls per minute). Try again shortly.")
        async with async_session_maker() as db:
            result = await work(db)
        return result if isinstance(result, dict) else {"result": result}
    except ToolError:
        raise
    except svc.McpToolError as exc:
        status = "error"
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 -- internals stay in the server log, not in the answer
        status = "error"
        logger.exception("MCP tool %s failed", tool)
        raise ToolError("Internal error; the failure was logged on the server.") from exc
    finally:
        await _log(caller, tool, args, status)


# ------------------------------------------------------------------ read tools


@mcp.tool()
async def list_projects() -> dict:
    """List the websites Helm tracks, with the slug every other tool takes."""
    return await _call("list_projects", "read", {}, lambda db: svc.list_projects(db))


@mcp.tool()
async def get_traffic(project: str, days: int = 28) -> dict:
    """Search Console and GA4 totals plus daily rows for the last `days` days (1-365) of collected data."""
    return await _call("get_traffic", "read", {"project": project, "days": days}, lambda db: svc.get_traffic(db, project, days))


@mcp.tool()
async def get_indexing_summary(project: str) -> dict:
    """Counts of URLs per indexing issue (indexed, thin, blocked, duplicate_risk, crawled_not_indexed, ...)."""
    return await _call("get_indexing_summary", "read", {"project": project}, lambda db: svc.get_indexing_summary(db, project))


@mcp.tool()
async def list_urls(project: str, issue: str | None = None, limit: int = 50) -> dict:
    """List sitemap URLs with their indexing issue; filter by `issue`; at most 200 rows."""
    return await _call("list_urls", "read", {"project": project, "issue": issue, "limit": limit}, lambda db: svc.list_urls(db, project, issue, limit))


@mcp.tool()
async def get_url_history(project: str, url: str) -> dict:
    """Inspection and page-signal history for one URL in the project's sitemap."""
    return await _call("get_url_history", "read", {"project": project, "url": url}, lambda db: svc.get_url_history(db, project, url))


@mcp.tool()
async def list_keyword_candidates(project: str, status: str | None = None) -> dict:
    """Keyword candidates ranked by score; filter by status (proposed, accepted, rejected, written)."""
    return await _call("list_keyword_candidates", "read", {"project": project, "status": status}, lambda db: svc.list_keyword_candidates(db, project, status))


@mcp.tool()
async def get_sitemap_status(project: str) -> dict:
    """Search Console's view of each submitted sitemap: last download, errors, warnings."""
    return await _call("get_sitemap_status", "read", {"project": project}, lambda db: svc.get_sitemap_status(db, project))


@mcp.tool()
async def get_keyword_run_status(project: str) -> dict:
    """The five most recent keyword generator runs for a project, to poll after run_keyword_generator."""
    return await _call("get_keyword_run_status", "read", {"project": project}, lambda db: svc.recent_runs(db, project))


# ------------------------------------------------------------------ write tools (write scope only)


@mcp.tool()
async def inspect_url(project: str, url: str) -> dict:
    """Queue a Search Console URL inspection. Counts against the daily budget; write scope only."""
    caller = current_caller.get()
    label = caller.label if caller else "unknown"
    return await _call("inspect_url", "write", {"project": project, "url": url}, lambda db: svc.inspect_url(db, project, url, label))


@mcp.tool()
async def run_keyword_generator(project: str) -> dict:
    """Start a keyword generation run in the background (spends the daily LLM budget); write scope only."""
    return await _call("run_keyword_generator", "write", {"project": project}, lambda db: svc.run_keyword_generator(db, project))


@mcp.tool()
async def set_candidate_status(candidate_id: str, status: str) -> dict:
    """Accept, reject or reopen a keyword candidate (accepted, rejected, proposed); write scope only."""
    return await _call("set_candidate_status", "write", {"candidate_id": candidate_id, "status": status}, lambda db: svc.set_candidate_status(db, candidate_id, status))


@mcp.tool()
async def export_keyword_queue(project: str) -> dict:
    """Export accepted keywords to the site's keyword queue; returns the queue. Write scope only."""
    return await _call("export_keyword_queue", "write", {"project": project}, lambda db: svc.export_keyword_queue(db, project))


# ------------------------------------------------------------------ HTTP app


class BearerTokenMiddleware:
    """Rejects any request without a valid, unrevoked Helm MCP token before it reaches the MCP handlers.
    The sync token and every other secret are unknown here: only `helm_` tokens in `mcp_tokens` pass."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/health":
            await JSONResponse({"status": "ok"})(scope, receive, send)
            return
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        scheme, _, raw = header.partition(" ")
        token = None
        if scheme.lower() == "bearer":
            async with async_session_maker() as db:
                token = await mcp_tokens.verify_token(db, raw)
        if token is None:
            response = JSONResponse({"error": "invalid or missing bearer token"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        reset = current_caller.set(Caller(token_id=str(token.id), label=token.label, scope=token.scope))
        try:
            await self.app(scope, receive, send)
        finally:
            current_caller.reset(reset)


def build_app() -> ASGIApp:
    hosts = settings.mcp_allowed_hosts
    inner = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,  # each call is independent, so the caller context set above is the one the tool sees
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[]),
    )
    return BearerTokenMiddleware(inner)
