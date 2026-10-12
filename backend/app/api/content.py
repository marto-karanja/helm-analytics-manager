"""The content dashboard: articles published and articles still queued, per pipeline, from the synced snapshots."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.users import current_active_user
from app.db.session import get_async_session
from app.models.project import PipelineSnapshot, Project
from app.models.user import User

router = APIRouter(dependencies=[Depends(current_active_user)])

HISTORY_POINTS = 30
RATE_WINDOW_DAYS = 28


class ContentPoint(BaseModel):
    at: datetime
    published: int | None
    queued: int | None


class ContentItem(BaseModel):
    project_id: str
    slug: str
    name: str
    url: str
    published: int | None
    queued: int | None
    blocked: int | None
    oldest_queued_days: int | None
    last_published_at: datetime | None
    last_synced_at: datetime | None
    severity: str | None
    published_per_day: float | None
    days_to_clear_queue: int | None
    history: list[ContentPoint]


class ContentTotals(BaseModel):
    published: int
    queued: int
    blocked: int
    published_per_day: float
    days_to_clear_queue: int | None
    pipelines: int
    pipelines_empty: int


class ContentDashboard(BaseModel):
    totals: ContentTotals
    items: list[ContentItem]


def _rate(snapshots: list[PipelineSnapshot]) -> float | None:
    """Articles published per day over the last RATE_WINDOW_DAYS of snapshots (newest first in `snapshots`).

    Uses the oldest snapshot inside the window that has a count; needs at least a day of span, and a count
    that went down (a pipeline reset or a recount) is treated as no information rather than a negative rate."""
    counted = [s for s in snapshots if s.total_articles_written is not None]
    if len(counted) < 2:
        return None
    newest = counted[0]
    window = [s for s in counted if s.synced_at >= newest.synced_at - timedelta(days=RATE_WINDOW_DAYS)]
    oldest = window[-1]
    days = (newest.synced_at - oldest.synced_at).total_seconds() / 86400
    if days < 1:
        return None
    gained = newest.total_articles_written - oldest.total_articles_written
    if gained < 0:
        return None
    return round(gained / days, 2)


def _days_to_clear(queued: int | None, rate: float | None) -> int | None:
    if queued is None or not rate:
        return None
    return round(queued / rate)


@router.get("/content/dashboard", response_model=ContentDashboard)
async def content_dashboard(
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_async_session)
) -> dict:
    projects = (
        await session.execute(
            select(Project)
            .where(Project.is_demo == user.is_demo, Project.is_pipeline.is_(True))
            .order_by(Project.name)
            .options(selectinload(Project.pipeline_snapshots))
        )
    ).scalars().all()

    items: list[dict] = []
    for project in projects:
        snaps = list(project.pipeline_snapshots)  # newest first
        latest = snaps[0] if snaps else None
        rate = _rate(snaps)
        queued = latest.backlog_count if latest else None
        items.append(
            {
                "project_id": str(project.id),
                "slug": project.slug,
                "name": project.name,
                "url": project.url,
                "published": latest.total_articles_written if latest else None,
                "queued": queued,
                "blocked": latest.blocked_count if latest else None,
                "oldest_queued_days": latest.oldest_backlog_age_days if latest else None,
                "last_published_at": latest.last_published_at if latest else None,
                "last_synced_at": latest.synced_at if latest else None,
                "severity": latest.alert_severity if latest else None,
                "published_per_day": rate,
                "days_to_clear_queue": _days_to_clear(queued, rate),
                "history": [
                    {"at": s.synced_at, "published": s.total_articles_written, "queued": s.backlog_count}
                    for s in reversed(snaps[:HISTORY_POINTS])
                ],
            }
        )

    total_rate = round(sum(i["published_per_day"] or 0 for i in items), 2)
    total_queued = sum(i["queued"] or 0 for i in items)
    totals = {
        "published": sum(i["published"] or 0 for i in items),
        "queued": total_queued,
        "blocked": sum(i["blocked"] or 0 for i in items),
        "published_per_day": total_rate,
        "days_to_clear_queue": _days_to_clear(total_queued, total_rate),
        "pipelines": len(items),
        "pipelines_empty": sum(1 for i in items if i["queued"] == 0),
    }
    return {"totals": totals, "items": items}
