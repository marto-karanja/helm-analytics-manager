"""Manual "Inspect now": validation, budget accounting and queueing, shared by the REST API and the MCP server."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import effective_budget, get_setting
from app.indexing.jobs import inspections_today
from app.models.indexing import InspectRequest, RollupRequest, SitemapUrl
from app.models.project import Project


class QueueError(Exception):
    """A refusal with the HTTP status the REST API should answer with."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


async def budget_state(session: AsyncSession) -> dict[str, int]:
    budget = effective_budget(await get_setting(session, "inspection_budget"))
    spent = sum((await inspections_today(session, datetime.now(timezone.utc))).values())
    queued = (
        await session.execute(select(func.count()).select_from(InspectRequest).where(InspectRequest.done_at.is_(None)))
    ).scalar_one()
    return {"budget": budget, "spent_today": spent, "queued": queued, "remaining": max(0, budget - spent - queued)}


async def queue_inspection(session: AsyncSession, project: Project, url: str, requested_by: str) -> dict:
    """Queues one inspection for the collector, which holds the Google credentials. Raises QueueError."""
    if not project.gsc_site_url:
        raise QueueError(409, "This project has no Search Console property")
    known = (
        await session.execute(
            select(SitemapUrl.id).where(SitemapUrl.project_id == project.id, SitemapUrl.url == url, SitemapUrl.removed_at.is_(None))
        )
    ).first()
    if known is None:
        raise QueueError(404, "That URL is not in the project's sitemap")
    already = (
        await session.execute(
            select(InspectRequest.id).where(
                InspectRequest.project_id == project.id, InspectRequest.url == url, InspectRequest.done_at.is_(None)
            )
        )
    ).first()
    if already is not None:
        raise QueueError(409, "An inspection for this URL is already queued")
    state = await budget_state(session)
    if state["remaining"] <= 0:
        raise QueueError(429, "Today's inspection budget is used up")
    request = InspectRequest(project_id=project.id, url=url, requested_by=requested_by)
    session.add(request)
    await session.commit()
    return {"queued": True, "id": request.id, "budget": {**state, "remaining": state["remaining"] - 1}}


MIN_MINUTES_BETWEEN_REFRESHES = 30


async def queue_rollup(session: AsyncSession, project: Project, requested_by: str, now: datetime | None = None) -> dict:
    """Queues an on-demand ranking refresh for the collector. One pending request per project, and at most one
    refresh per project every 30 minutes, so a loop in a script cannot hammer the Search Console API."""
    now = now or datetime.now(timezone.utc)
    if not project.gsc_site_url:
        raise QueueError(409, "This project has no Search Console property")
    pending = (
        await session.execute(select(RollupRequest.id).where(RollupRequest.project_id == project.id, RollupRequest.done_at.is_(None)))
    ).first()
    if pending is not None:
        raise QueueError(409, "A refresh for this project is already queued")
    last = (await session.execute(select(func.max(RollupRequest.requested_at)).where(RollupRequest.project_id == project.id))).scalar_one()
    if last is not None and now - last < timedelta(minutes=MIN_MINUTES_BETWEEN_REFRESHES):
        wait = MIN_MINUTES_BETWEEN_REFRESHES - int((now - last).total_seconds() // 60)
        raise QueueError(429, f"A refresh was requested recently; try again in about {wait} minutes")
    request = RollupRequest(project_id=project.id, requested_by=requested_by)
    session.add(request)
    await session.commit()
    return {"queued": True, "id": request.id, "note": "The collector runs queued refreshes within about a minute; poll the rankings for last_refreshed_at."}
