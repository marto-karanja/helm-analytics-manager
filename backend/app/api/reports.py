import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_setting
from app.core.csv_export import to_csv
from app.core.users import current_active_user
from app.db.session import get_async_session
from app.indexing import classify as rules
from app.indexing import service
from app.keywords import queries
from app.models.indexing import WeeklyDigest
from app.models.project import Project
from app.models.user import User

router = APIRouter()

REPORTS = ("indexing", "non-indexed", "striking-distance", "digest")
HEALTHY = {rules.INDEXED, rules.UNKNOWN}


async def _projects(session: AsyncSession, user: User, slug: str | None) -> list[Project]:
    stmt = select(Project).where(Project.is_demo == user.is_demo, Project.is_pipeline.is_(True)).order_by(Project.name)
    if slug:
        stmt = stmt.where(Project.slug == slug)
    projects = list((await session.execute(stmt)).scalars().all())
    if slug and not projects:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return projects


async def build_report(session: AsyncSession, user: User, name: str, slug: str | None) -> dict[str, Any]:
    projects = await _projects(session, user, slug)
    thin = await get_setting(session, "thin_word_threshold")

    if name == "indexing":
        columns = ["project", "total_urls", *rules.ISSUES, "indexed_percent"]
        rows = []
        for p in projects:
            counts = service.count_issues(await service.url_statuses(session, p.id, thin))
            rows.append([p.name, sum(counts.values()), *[counts[i] for i in rules.ISSUES], service.indexed_percent(counts)])
        return {"name": name, "columns": columns, "rows": rows}

    if name == "non-indexed":
        columns = ["project", "url", "issue", "coverage_state", "last_crawl_time", "word_count", "http_status", "title"]
        rows = []
        for p in projects:
            for r in await service.url_statuses(session, p.id, thin):
                if r["issue"] not in HEALTHY:
                    rows.append([p.name, r["url"], r["issue"], r["coverage_state"], r["last_crawl_time"], r["word_count"], r["http_status"], r["title"]])
        rows.sort(key=lambda r: (r[0], r[2], r[1]))
        return {"name": name, "columns": columns, "rows": rows}

    if name == "striking-distance":
        columns = ["project", "query", "page", "position", "impressions", "clicks"]
        rows = []
        for p in projects:
            for s in queries.striking_distance(await queries.query_stats(session, p.id)):
                rows.append([p.name, s.query, s.top_page, s.position, s.impressions, s.clicks])
        return {"name": name, "columns": columns, "rows": rows}

    # digest: the stored weekly snapshots, newest first
    columns = ["project", "week_start", "clicks", "clicks_change_pct", "impressions", "impressions_change_pct", "indexed_percent", "striking_distance", "pending_keywords"]
    rows = []
    for p in projects:
        digests = (
            await session.execute(select(WeeklyDigest).where(WeeklyDigest.project_id == p.id).order_by(WeeklyDigest.week_start.desc()).limit(26))
        ).scalars()
        for d in digests:
            t = d.payload.get("traffic", {})
            rows.append([
                p.name, d.week_start, t.get("clicks"), t.get("clicks_change_pct"), t.get("impressions"), t.get("impressions_change_pct"),
                d.payload.get("indexing", {}).get("indexed_percent"), d.payload.get("striking_distance"), d.payload.get("pending_keyword_candidates"),
            ])
    rows.sort(key=lambda r: (r[1], r[0]), reverse=True)
    return {"name": name, "columns": columns, "rows": rows}


@router.get("/reports/{name}")
async def get_report(
    name: str,
    project: str | None = Query(None, max_length=100),
    format: str = Query("json", pattern="^(json|csv)$"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    if name not in REPORTS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown report; choose one of {', '.join(REPORTS)}")
    report = await build_report(session, user, name, project)
    if format == "csv":
        safe = re.sub(r"[^A-Za-z0-9_-]", "", f"{name}-{project or 'all'}")
        return Response(
            to_csv(report["columns"], report["rows"]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="helm-{safe}-{date.today().isoformat()}.csv"'},
        )
    return report


@router.get("/reports/digest/{project_slug}/{week}")
async def get_digest(
    project_slug: str,
    week: date,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    (project,) = await _projects(session, user, project_slug)
    digest = (
        await session.execute(select(WeeklyDigest).where(WeeklyDigest.project_id == project.id, WeeklyDigest.week_start == week))
    ).scalar_one_or_none()
    if digest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No digest for that week")
    return digest.payload
