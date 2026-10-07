"""What the MCP tools do. Calls Helm's service layer directly (no HTTP to itself) and returns plain data:
never credentials, never key-file contents, never raw table dumps."""
import uuid
from datetime import date, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_setting
from app.indexing import classify as rules
from app.indexing import manual, service
from app.keywords import export as export_mod
from app.keywords import generator
from app.keywords import llm as llm_mod
from app.keywords.launch import launch_run
from app.models.indexing import KeywordCandidate, KeywordRun, PageSignal, SitemapStatus, SitemapUrl, UrlInspection
from app.models.project import Project, TrafficDaily

MAX_LIST = 200
MAX_TRAFFIC_DAYS = 365
CANDIDATE_STATUSES = ("proposed", "accepted", "rejected", "written")
SETTABLE_STATUSES = ("proposed", "accepted", "rejected")


class McpToolError(Exception):
    """A refusal whose message is safe to show the client."""


def _plain(value: Any) -> Any:
    return jsonable_encoder(value)


async def find_project(db: AsyncSession, slug: str) -> Project:
    project = (
        await db.execute(select(Project).where(Project.slug == slug, Project.is_demo.is_(False)))
    ).scalar_one_or_none()
    if project is None:
        raise McpToolError(f"No project with slug {slug!r}. Use list_projects to see the valid slugs.")
    return project


async def list_projects(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(Project).where(Project.is_demo.is_(False)).order_by(Project.name))).scalars().all()
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "url": p.url,
            "category": p.category,
            "search_console": bool(p.gsc_site_url),
            "ga4": bool(p.ga4_property_id),
        }
        for p in rows
    ]


async def get_traffic(db: AsyncSession, slug: str, days: int) -> dict:
    project = await find_project(db, slug)
    if not 1 <= days <= MAX_TRAFFIC_DAYS:
        raise McpToolError(f"days must be between 1 and {MAX_TRAFFIC_DAYS}")
    newest = (await db.execute(select(func.max(TrafficDaily.metric_date)).where(TrafficDaily.project_id == project.id))).scalar_one()
    if newest is None:
        return {"project": slug, "days": 0, "totals": None, "daily": [], "note": "no traffic collected yet"}
    rows = (
        await db.execute(
            select(TrafficDaily)
            .where(TrafficDaily.project_id == project.id, TrafficDaily.metric_date > newest - timedelta(days=days))
            .order_by(TrafficDaily.metric_date)
        )
    ).scalars().all()
    return _plain(
        {
            "project": slug,
            "through": newest,
            "days": len(rows),
            "totals": {
                "clicks": sum(r.clicks or 0 for r in rows),
                "impressions": sum(r.impressions or 0 for r in rows),
                "sessions": sum(r.sessions or 0 for r in rows),
            },
            "daily": [
                {"date": r.metric_date, "clicks": r.clicks, "impressions": r.impressions, "position": r.avg_position, "sessions": r.sessions}
                for r in rows
            ],
        }
    )


async def get_indexing_summary(db: AsyncSession, slug: str) -> dict:
    project = await find_project(db, slug)
    thin = await get_setting(db, "thin_word_threshold")
    rows = await service.url_statuses(db, project.id, thin)
    counts = service.count_issues(rows)
    return _plain(
        {
            "project": slug,
            "total_urls": len(rows),
            "counts": counts,
            "indexed_percent": service.indexed_percent(counts),
            "thin_word_threshold": thin,
        }
    )


async def list_urls(db: AsyncSession, slug: str, issue: str | None, limit: int) -> dict:
    project = await find_project(db, slug)
    if issue is not None and issue not in rules.ISSUES:
        raise McpToolError(f"issue must be one of: {', '.join(rules.ISSUES)}")
    limit = max(1, min(limit, MAX_LIST))
    rows = await service.url_statuses(db, project.id, await get_setting(db, "thin_word_threshold"))
    if issue:
        rows = [r for r in rows if r["issue"] == issue]
    keep = ("url", "issue", "coverage_state", "last_crawl_time", "word_count", "http_status", "title")
    return _plain({"project": slug, "total": len(rows), "returned": min(limit, len(rows)), "urls": [{k: r[k] for k in keep} for r in rows[:limit]]})


async def get_url_history(db: AsyncSession, slug: str, url: str) -> dict:
    project = await find_project(db, slug)
    known = (await db.execute(select(SitemapUrl.id).where(SitemapUrl.project_id == project.id, SitemapUrl.url == url))).first()
    if known is None:
        raise McpToolError("That URL is not in the project's sitemap.")
    inspections = (
        await db.execute(
            select(UrlInspection).where(UrlInspection.project_id == project.id, UrlInspection.url == url).order_by(UrlInspection.inspected_at.desc()).limit(30)
        )
    ).scalars().all()
    signals = (
        await db.execute(select(PageSignal).where(PageSignal.project_id == project.id, PageSignal.url == url).order_by(PageSignal.fetched_at.desc()).limit(10))
    ).scalars().all()
    return _plain(
        {
            "url": url,
            "inspections": [
                {"at": i.inspected_at, "verdict": i.verdict, "coverage_state": i.coverage_state, "last_crawl_time": i.last_crawl_time, "page_fetch_state": i.page_fetch_state}
                for i in inspections
            ],
            "signals": [
                {"at": s.fetched_at, "http_status": s.http_status, "title": s.title, "word_count": s.word_count, "noindex": s.noindex, "canonical": s.canonical, "error": s.error}
                for s in signals
            ],
        }
    )


async def list_keyword_candidates(db: AsyncSession, slug: str, status: str | None, limit: int = 100) -> dict:
    project = await find_project(db, slug)
    if status is not None and status not in CANDIDATE_STATUSES:
        raise McpToolError(f"status must be one of: {', '.join(CANDIDATE_STATUSES)}")
    stmt = select(KeywordCandidate).where(KeywordCandidate.project_id == project.id)
    if status:
        stmt = stmt.where(KeywordCandidate.status == status)
    rows = (await db.execute(stmt.order_by(KeywordCandidate.score.desc()).limit(max(1, min(limit, MAX_LIST))))).scalars().all()
    return _plain(
        {
            "project": slug,
            "candidates": [
                {
                    "id": c.id, "keyword": c.keyword, "status": c.status, "score": c.score, "intent": c.intent, "cluster": c.cluster_label,
                    "volume": c.volume, "volume_is_bucket": c.volume_is_bucket, "demand_source": c.demand_source,
                    "impressions": c.impressions_proxy, "position": c.position_avg, "gap": c.gap, "target_url": c.target_url,
                }
                for c in rows
            ],
        }
    )


async def get_sitemap_status(db: AsyncSession, slug: str) -> dict:
    project = await find_project(db, slug)
    rows = (await db.execute(select(SitemapStatus).where(SitemapStatus.project_id == project.id).order_by(SitemapStatus.path))).scalars().all()
    return _plain(
        {
            "project": slug,
            "sitemaps": [
                {"path": s.path, "last_submitted": s.last_submitted, "last_downloaded": s.last_downloaded, "pending": s.is_pending, "errors": s.errors, "warnings": s.warnings, "submitted_urls": s.submitted_urls}
                for s in rows
            ],
        }
    )


# ------------------------------------------------------------------ write tools


async def inspect_url(db: AsyncSession, slug: str, url: str, requested_by: str) -> dict:
    project = await find_project(db, slug)
    try:
        result = await manual.queue_inspection(db, project, url, f"mcp:{requested_by}")
    except manual.QueueError as exc:
        raise McpToolError(exc.detail) from exc
    return _plain({"queued": True, "budget": result["budget"], "note": "The collector runs queued inspections within about a minute."})


async def run_keyword_generator(db: AsyncSession, slug: str) -> dict:
    project = await find_project(db, slug)
    try:
        run = await launch_run(db, project)
    except (llm_mod.DailyCapReached, generator.GeneratorError) as exc:
        raise McpToolError(str(exc)) from exc
    return _plain({"run_id": run.id, "status": run.status, "note": "Poll list_keyword_candidates for the results."})


async def set_candidate_status(db: AsyncSession, candidate_id: str, status: str) -> dict:
    if status not in SETTABLE_STATUSES:
        raise McpToolError(f"status must be one of: {', '.join(SETTABLE_STATUSES)}")
    try:
        key = uuid.UUID(candidate_id)
    except ValueError as exc:
        raise McpToolError("candidate_id must be a UUID from list_keyword_candidates") from exc
    candidate = await db.get(KeywordCandidate, key)
    project = await db.get(Project, candidate.project_id) if candidate else None
    if candidate is None or project is None or project.is_demo:
        raise McpToolError("No such candidate.")
    if candidate.status == "written":
        raise McpToolError("That keyword was already exported to the queue file.")
    from datetime import datetime, timezone

    candidate.status = status
    candidate.decided_at = None if status == "proposed" else datetime.now(timezone.utc)
    await db.commit()
    return {"id": str(candidate.id), "keyword": candidate.keyword, "status": candidate.status}


async def export_keyword_queue(db: AsyncSession, slug: str) -> dict:
    project = await find_project(db, slug)
    result = await export_mod.export_queue(db, project)
    return _plain({"exported": result["count"], "file_written": result["path"] is not None, "queue": result["payload"]})


async def recent_runs(db: AsyncSession, slug: str) -> list[dict]:
    project = await find_project(db, slug)
    rows = (await db.execute(select(KeywordRun).where(KeywordRun.project_id == project.id).order_by(KeywordRun.started_at.desc()).limit(5))).scalars().all()
    return _plain([{"id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at, "error": r.error} for r in rows])
