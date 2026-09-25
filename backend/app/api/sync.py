from datetime import date, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import verify_sync_token
from app.db.session import get_async_session
from app.models.project import PipelineSnapshot, Project
from app.schemas.sync import PipelineSyncItem, PortfolioSyncItem, SyncPayload

router = APIRouter(dependencies=[Depends(verify_sync_token)])


async def _upsert_portfolio_project(session: AsyncSession, item: PortfolioSyncItem) -> bool:
    """Returns True if created, False if updated."""
    result = await session.execute(select(Project).where(Project.slug == item.slug))
    project = result.scalar_one_or_none()
    last_updated = date.fromisoformat(item.last_updated) if item.last_updated else None

    if project is None:
        session.add(
            Project(
                slug=item.slug,
                name=item.name,
                category=item.category,
                url=item.url,
                local_repo=item.local_repo,
                operational_signals=item.operational_signals,
                last_updated=last_updated,
                goals=item.goals,
                current_status=item.current_status,
                blockers=item.blockers,
                priority_notes=item.priority_notes,
                is_pipeline=False,
            )
        )
        return True

    # goals/current_status/blockers/priority_notes are user-editable via the
    # UI once seeded -- re-syncing the markdown must not clobber them.
    project.name = item.name
    project.category = item.category
    project.url = item.url
    project.local_repo = item.local_repo
    project.operational_signals = item.operational_signals
    project.last_updated = last_updated
    return False


async def _upsert_pipeline_project(session: AsyncSession, item: PipelineSyncItem) -> tuple[Project, bool]:
    """Returns (project, created)."""
    result = await session.execute(select(Project).where(Project.slug == item.slug))
    project = result.scalar_one_or_none()

    if project is None:
        project = Project(
            slug=item.slug,
            name=item.name,
            category="seo-content-site",
            url=item.url,
            is_pipeline=True,
        )
        session.add(project)
        await session.flush()
        return project, True

    # gsc_site_url / ga4_property_id are owned by Helm's database (set via the
    # CLI and read by the collector) -- the sync must never touch them.
    project.is_pipeline = True
    project.url = item.url
    return project, False


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def receive_sync(
    payload: SyncPayload, session: AsyncSession = Depends(get_async_session)
) -> dict[str, int]:
    portfolio_created = portfolio_updated = 0
    pipelines_created = pipelines_updated = 0

    for item in payload.portfolio:
        if await _upsert_portfolio_project(session, item):
            portfolio_created += 1
        else:
            portfolio_updated += 1

    for item in payload.pipelines:
        project, created = await _upsert_pipeline_project(session, item)
        pipelines_created += created
        pipelines_updated += not created

        last_published_at = (
            datetime.fromisoformat(item.metrics.last_published_at) if item.metrics.last_published_at else None
        )
        session.add(
            PipelineSnapshot(
                project_id=project.id,
                total_articles_written=item.metrics.total_articles_written,
                backlog_count=item.metrics.backlog_count,
                blocked_count=item.metrics.blocked_count,
                oldest_backlog_age_days=item.metrics.oldest_backlog_age_days,
                last_published_at=last_published_at,
                last_7_runs=item.metrics.last_7_runs,
                alert_severity=item.pipeline_alert_severity,
                alert_messages=item.pipeline_alert_messages,
            )
        )

    await session.commit()
    return {
        "portfolio_created": portfolio_created,
        "portfolio_updated": portfolio_updated,
        "pipelines_created": pipelines_created,
        "pipelines_updated": pipelines_updated,
    }
