import re
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csv_export import to_csv
from app.core.users import current_active_user
from app.db.session import get_async_session
from app.models.indexing import WeeklyDigest
from app.models.project import Project
from app.models.user import User
from app.reports import availability, builders
from app.reports.catalog import BY_NAME, CATALOG, GRANULARITIES, NAMES
from app.reports.compare import compare_reports

router = APIRouter()

REPORTS = NAMES  # kept for callers that import it


async def _projects(session: AsyncSession, user: User, slug: str | None) -> list[Project]:
    stmt = select(Project).where(Project.is_demo == user.is_demo, Project.is_pipeline.is_(True)).order_by(Project.name)
    if slug:
        stmt = stmt.where(Project.slug == slug)
    projects = list((await session.execute(stmt)).scalars().all())
    if slug and not projects:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return projects


def _resolve_date(value: date | None, name: str, today: date) -> date:
    """Today when absent. A day ahead of UTC is tolerated (a reader east of Greenwich), further ahead is refused."""
    if value is None:
        return today
    if value > today + timedelta(days=1):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{name} cannot be in the future")
    return min(value, today)


def _check_name(name: str) -> None:
    if name not in BY_NAME:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown report; choose one of {', '.join(NAMES)}")


def _params(as_of: date, today: date, granularity: str, days: int, weeks: int, latest_week_only: bool = False) -> builders.Params:
    if granularity not in GRANULARITIES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"granularity must be one of: {', '.join(GRANULARITIES)}")
    return builders.Params(as_of=as_of, today=today, granularity=granularity, days=days, weeks=weeks, latest_week_only=latest_week_only)


def _csv(report: dict[str, Any], filename: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", filename)
    return Response(
        to_csv(report["columns"], report["rows"]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="helm-{safe}.csv"'},
    )


@router.get("/reports/catalog")
async def report_catalog(user: User = Depends(current_active_user)) -> dict[str, Any]:
    """Every report, how it is compared, and where its history comes from."""
    return {
        "reports": [
            {"name": s.name, "label": s.label, "blurb": s.blurb, "kind": s.kind, "compare_keys": list(s.keys), "history": s.history}
            for s in CATALOG
        ],
        "granularities": list(GRANULARITIES),
    }


@router.get("/reports/availability")
async def report_availability(
    project: str | None = Query(None, max_length=100),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """The first and last date each report can answer for, so a date picker can refuse impossible dates."""
    projects = await _projects(session, user, project)
    today = builders.today_utc()
    out = {}
    for spec in CATALOG:
        first, last = await availability.bounds(session, spec.name, [p.id for p in projects], today)
        out[spec.name] = {"label": spec.label, "kind": spec.kind, "from": first, "to": last, "history": spec.history}
    return {"today": today, "reports": out}


@router.get("/reports/{name}")
async def get_report(
    name: str,
    project: str | None = Query(None, max_length=100),
    format: str = Query("json", pattern="^(json|csv)$"),
    as_of: date | None = Query(None, description="The state on this UTC date (inclusive); default today"),
    days: int = Query(builders.DEFAULT_TRAFFIC_DAYS, ge=1, le=builders.MAX_TRAFFIC_DAYS, description="Traffic: period length ending on the date"),
    granularity: str = Query("total", description="Traffic: total, day, week or month"),
    weeks: int = Query(builders.DEFAULT_DIGEST_WEEKS, ge=1, le=builders.MAX_DIGEST_WEEKS, description="Digest: how many weeks to list"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    _check_name(name)
    today = builders.today_utc()
    day = _resolve_date(as_of, "as_of", today)
    projects = await _projects(session, user, project)
    report = (await builders.build(session, projects, name, _params(day, today, granularity, days, weeks))).as_dict()
    if format == "csv":
        return _csv(report, f"{name}-{project or 'all'}-{day.isoformat()}")
    return report


@router.get("/reports/{name}/compare")
async def compare_report(
    name: str,
    a: date = Query(..., description="First date (UTC)"),
    b: date = Query(..., description="Second date (UTC)"),
    project: str | None = Query(None, max_length=100),
    format: str = Query("json", pattern="^(json|csv)$"),
    changed_only: bool = Query(False, description="Leave out rows that are identical at both dates"),
    days: int = Query(builders.DEFAULT_TRAFFIC_DAYS, ge=1, le=builders.MAX_TRAFFIC_DAYS),
    granularity: str = Query("total"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """The same report at two dates, matched row by row: new, gone, changed or same, with deltas for numbers.
    For traffic, each date ends a period of `days` days."""
    _check_name(name)
    today = builders.today_utc()
    day_a, day_b = _resolve_date(a, "a", today), _resolve_date(b, "b", today)
    projects = await _projects(session, user, project)
    latest_only = name == "digest"
    report_a = await builders.build(session, projects, name, _params(day_a, today, granularity, days, 1, latest_only))
    report_b = await builders.build(session, projects, name, _params(day_b, today, granularity, days, 1, latest_only))
    result = compare_reports(report_a, report_b, BY_NAME[name].keys, changed_only)
    result["meta"] = {
        "a": report_a.meta,
        "b": report_b.meta,
        "notes": [n for n in (report_a.meta.get("note"), report_b.meta.get("note")) if n],
        "change_column": "new = only at B, gone = only at A. For positions a negative delta means the page moved up.",
    }
    if format == "csv":
        return _csv(result, f"{name}-compare-{project or 'all'}-{day_a.isoformat()}-{day_b.isoformat()}")
    return result


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
