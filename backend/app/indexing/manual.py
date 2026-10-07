"""Manual "Inspect now": validation, budget accounting and queueing, shared by the REST API and the MCP server."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import effective_budget, get_setting
from app.indexing.jobs import inspections_today
from app.models.indexing import InspectRequest, SitemapUrl
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
