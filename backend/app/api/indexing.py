import uuid

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import get_project, require_owner
from app.core.app_settings import get_setting
from app.core.users import current_active_user
from app.db.session import get_async_session
from app.indexing import classify as rules
from app.indexing import manual, rankings, service
from app.models.indexing import IndexingSnapshot, PageSignal, SitemapStatus, SitemapUrl, UrlInspection
from app.models.project import Project
from app.models.user import User

router = APIRouter(dependencies=[Depends(current_active_user)])

HISTORY_DAYS = 90
MAX_PAGE = 500


class InspectBody(BaseModel):
    url: str



@router.get("/projects/{project_id}/indexing")
async def get_indexing_summary(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_async_session)
) -> dict[str, Any]:
    thin = await get_setting(session, "thin_word_threshold")
    rows = await service.url_statuses(session, project.id, thin)
    counts = service.count_issues(rows)
    history = (
        await session.execute(
            select(IndexingSnapshot)
            .where(IndexingSnapshot.project_id == project.id)
            .order_by(IndexingSnapshot.snapshot_date.desc())
            .limit(HISTORY_DAYS)
        )
    ).scalars()
    last_walk = (
        await session.execute(select(func.max(SitemapUrl.last_seen_at)).where(SitemapUrl.project_id == project.id))
    ).scalar_one()
    last_inspection = (
        await session.execute(select(func.max(UrlInspection.inspected_at)).where(UrlInspection.project_id == project.id))
    ).scalar_one()
    return {
        "total": len(rows),
        "counts": counts,
        "indexed_percent": service.indexed_percent(counts),
        "thin_word_threshold": thin,
        "history": [
            {"date": h.snapshot_date, "total": h.total_urls, "counts": h.counts} for h in reversed(list(history))
        ],
        "last_sitemap_walk_at": last_walk,
        "last_inspection_at": last_inspection,
        "budget": await manual.budget_state(session),
        "has_search_console": bool(project.gsc_site_url),
    }


@router.get("/projects/{project_id}/indexing/urls")
async def list_indexing_urls(
    issue: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    if issue is not None and issue not in rules.ISSUES:
        raise HTTPException(status_code=422, detail=f"issue must be one of {', '.join(rules.ISSUES)}")
    thin = await get_setting(session, "thin_word_threshold")
    rows = await service.url_statuses(session, project.id, thin)
    if issue:
        rows = [r for r in rows if r["issue"] == issue]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r["url"].lower() or needle in (r["title"] or "").lower()]
    return {"total": len(rows), "items": rows[offset : offset + limit]}


@router.get("/projects/{project_id}/indexing/urls/{url_id}")
async def get_indexing_url(
    url_id: uuid.UUID, project: Project = Depends(get_project), session: AsyncSession = Depends(get_async_session)
) -> dict[str, Any]:
    row = (
        await session.execute(select(SitemapUrl).where(SitemapUrl.id == url_id, SitemapUrl.project_id == project.id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    inspections = (
        await session.execute(
            select(UrlInspection)
            .where(UrlInspection.project_id == project.id, UrlInspection.url == row.url)
            .order_by(UrlInspection.inspected_at.desc())
            .limit(50)
        )
    ).scalars().all()
    signals = (
        await session.execute(
            select(PageSignal)
            .where(PageSignal.project_id == project.id, PageSignal.url == row.url)
            .order_by(PageSignal.fetched_at.desc())
            .limit(20)
        )
    ).scalars().all()
    thin = await get_setting(session, "thin_word_threshold")
    status_row = next((r for r in await service.url_statuses(session, project.id, thin) if r["id"] == row.id), None)
    return {
        "id": row.id,
        "url": row.url,
        "issue": status_row["issue"] if status_row else None,
        "lastmod": row.lastmod,
        "first_seen_at": row.first_seen_at,
        "inspections": [
            {
                "inspected_at": i.inspected_at,
                "verdict": i.verdict,
                "coverage_state": i.coverage_state,
                "indexing_state": i.indexing_state,
                "robots_txt_state": i.robots_txt_state,
                "page_fetch_state": i.page_fetch_state,
                "last_crawl_time": i.last_crawl_time,
                "crawled_as": i.crawled_as,
                "google_canonical": i.google_canonical,
            }
            for i in inspections
        ],
        "signals": [
            {
                "fetched_at": s.fetched_at,
                "http_status": s.http_status,
                "title": s.title,
                "meta_description": s.meta_description,
                "word_count": s.word_count,
                "h1_count": s.h1_count,
                "h2_count": s.h2_count,
                "internal_links": s.internal_links,
                "canonical": s.canonical,
                "noindex": s.noindex,
                "source": s.source,
                "error": s.error,
            }
            for s in signals
        ],
    }


@router.post("/projects/{project_id}/indexing/inspect", status_code=status.HTTP_202_ACCEPTED)
async def inspect_now(
    body: InspectBody,
    project: Project = Depends(get_project),
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Queues one inspection. The collector holds the Google credentials and runs it on its next tick."""
    try:
        return await manual.queue_inspection(session, project, body.url, user.email)
    except manual.QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/projects/{project_id}/rankings")
async def get_rankings(
    weeks: int = Query(4, ge=1, le=rankings.MAX_WEEKS),
    min_impressions: int = Query(10, ge=0),
    limit: int = Query(100, ge=1, le=rankings.MAX_PAGES),
    url: str | None = None,
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Per-page positions from the weekly rollups, with when they were last refreshed."""
    return jsonable_encoder(await rankings.page_rankings(session, project, weeks, min_impressions, limit, url))


@router.post("/projects/{project_id}/rankings/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_rankings(
    project: Project = Depends(get_project),
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """The manual alternative to the weekly rollup. The collector holds the Google credentials and runs it on its next tick."""
    try:
        return await manual.queue_rollup(session, project, user.email)
    except manual.QueueError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/projects/{project_id}/sitemaps")
async def get_sitemaps(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_async_session)
) -> dict[str, Any]:
    sitemaps = (
        await session.execute(select(SitemapStatus).where(SitemapStatus.project_id == project.id).order_by(SitemapStatus.path))
    ).scalars().all()
    found = dict(
        (
            await session.execute(
                select(SitemapUrl.source_sitemap, func.count())
                .where(SitemapUrl.project_id == project.id, SitemapUrl.removed_at.is_(None))
                .group_by(SitemapUrl.source_sitemap)
            )
        ).all()
    )
    return {
        "has_search_console": bool(project.gsc_site_url),
        "sitemaps": [
            {
                "path": s.path,
                "last_submitted": s.last_submitted,
                "last_downloaded": s.last_downloaded,
                "is_pending": s.is_pending,
                "errors": s.errors,
                "warnings": s.warnings,
                "submitted_urls": s.submitted_urls,
                "indexed_urls": s.indexed_urls,
                "urls_found_by_helm": found.get(s.path, 0),
                "fetched_at": s.fetched_at,
            }
            for s in sitemaps
        ],
        "urls_by_source": [{"sitemap": k, "urls": v} for k, v in sorted(found.items(), key=lambda kv: str(kv[0]))],
    }


@router.get("/indexing/overview")
async def indexing_overview(
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_async_session)
) -> list[dict[str, Any]]:
    """One row per pipeline project for the Overview cards: indexed share, problem counts, pending keywords."""
    from app.models.indexing import KeywordCandidate

    thin = await get_setting(session, "thin_word_threshold")
    projects = (
        await session.execute(
            select(Project).where(Project.is_demo == user.is_demo, Project.is_pipeline.is_(True)).order_by(Project.name)
        )
    ).scalars().all()
    pending = dict(
        (
            await session.execute(
                select(KeywordCandidate.project_id, func.count())
                .where(KeywordCandidate.status == "proposed")
                .group_by(KeywordCandidate.project_id)
            )
        ).all()
    )
    items = []
    for project in projects:
        counts = service.count_issues(await service.url_statuses(session, project.id, thin))
        items.append(
            {
                "project_id": project.id,
                "slug": project.slug,
                "total_urls": sum(counts.values()),
                "indexed_percent": service.indexed_percent(counts),
                "thin": counts[rules.THIN],
                "crawled_not_indexed": counts[rules.CRAWLED_NOT_INDEXED],
                "pending_keywords": pending.get(project.id, 0),
            }
        )
    return items
