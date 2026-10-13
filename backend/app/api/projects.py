import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.users import current_active_user
from app.db.session import get_async_session
from app.models.project import Project, Task, TrafficDaily, TrafficSnapshot
from app.models.user import User
from app.schemas.project import (
    ProjectDetailRead,
    ProjectRead,
    ProjectUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TaskWithProjectRead,
    TrafficOverviewItem,
    TrafficRead,
)

router = APIRouter(dependencies=[Depends(current_active_user)])

SNAPSHOT_HISTORY_LIMIT = 30
CLICKS_SERIES_DAYS = 28


def _require_write_access(user: User) -> None:
    if user.is_demo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Demo account is read-only")


@router.get("/projects", response_model=list[ProjectRead])
async def list_projects(
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_async_session)
) -> list[Project]:
    result = await session.execute(
        select(Project)
        .where(Project.is_demo == user.is_demo)
        .order_by(Project.name)
        .options(selectinload(Project.tasks), selectinload(Project.pipeline_snapshots))
    )
    projects = list(result.scalars().all())
    for project in projects:
        project.latest_alert_severity = (
            project.pipeline_snapshots[0].alert_severity if project.pipeline_snapshots else None
        )
        project.open_task_count = sum(1 for t in project.tasks if t.status != "done")
    return projects


@router.get("/tasks", response_model=list[TaskWithProjectRead])
async def list_open_tasks(
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_async_session)
) -> list[Task]:
    priority_rank = case({"high": 0, "normal": 1, "low": 2}, value=Task.priority, else_=1)
    result = await session.execute(
        select(Task)
        .join(Project)
        .where(Task.status != "done", Project.is_demo == user.is_demo)
        .options(selectinload(Task.project))
        .order_by(priority_rank, Task.created_at)
    )
    tasks = list(result.scalars().all())
    for task in tasks:
        task.project_name = task.project.name
        task.project_slug = task.project.slug
    return tasks


@router.get("/projects/{project_id}", response_model=ProjectDetailRead)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Project:
    result = await session.execute(
        select(Project)
        .where(Project.id == project_id, Project.is_demo == user.is_demo)
        .options(
            selectinload(Project.tasks),
            selectinload(Project.pipeline_snapshots),
            selectinload(Project.traffic_snapshots),
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project.latest_alert_severity = (
        project.pipeline_snapshots[0].alert_severity if project.pipeline_snapshots else None
    )
    project.open_task_count = sum(1 for t in project.tasks if t.status != "done")
    project.pipeline_snapshots = project.pipeline_snapshots[:SNAPSHOT_HISTORY_LIMIT]
    project.traffic_snapshots = project.traffic_snapshots[:SNAPSHOT_HISTORY_LIMIT]
    project.traffic_last_collected_at = await _last_collected_at(session, project.id)
    return project


async def _last_collected_at(session: AsyncSession, project_id: uuid.UUID) -> datetime | None:
    # From the data rows, not TrafficSnapshot.synced_at: a run whose pull failed still writes a
    # snapshot, and that must not make stale data look freshly collected.
    return (
        await session.execute(select(func.max(TrafficDaily.updated_at)).where(TrafficDaily.project_id == project_id))
    ).scalar_one()


@router.get("/projects/{project_id}/traffic", response_model=TrafficRead)
async def get_project_traffic(
    project_id: uuid.UUID,
    days: int = Query(90, ge=1, le=500),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    project = (
        await session.execute(select(Project.id).where(Project.id == project_id, Project.is_demo == user.is_demo))
    ).first()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    newest = (
        await session.execute(select(func.max(TrafficDaily.metric_date)).where(TrafficDaily.project_id == project_id))
    ).scalar_one()
    rows: list[TrafficDaily] = []
    if newest is not None:
        # Anchored on the newest stored day (not today) so the window is stable, and calendar-based so
        # days the source skipped stay gaps in the chart instead of pulling in older rows.
        result = await session.execute(
            select(TrafficDaily)
            .where(TrafficDaily.project_id == project_id, TrafficDaily.metric_date > newest - timedelta(days=days))
            .order_by(TrafficDaily.metric_date)
        )
        rows = list(result.scalars().all())
    return {"days": rows, "last_collected_at": await _last_collected_at(session, project_id)}


async def _clicks_series(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[int | None]]:
    """Per project, the last CLICKS_SERIES_DAYS calendar days of clicks ending at its newest stored day (gaps are None)."""
    if not project_ids:
        return {}
    newest = dict(
        (
            await session.execute(
                select(TrafficDaily.project_id, func.max(TrafficDaily.metric_date))
                .where(TrafficDaily.project_id.in_(project_ids))
                .group_by(TrafficDaily.project_id)
            )
        ).all()
    )
    if not newest:
        return {}
    earliest = min(newest.values()) - timedelta(days=CLICKS_SERIES_DAYS - 1)
    rows = (
        await session.execute(
            select(TrafficDaily.project_id, TrafficDaily.metric_date, TrafficDaily.clicks).where(
                TrafficDaily.project_id.in_(newest), TrafficDaily.metric_date >= earliest
            )
        )
    ).all()
    by_project: dict[uuid.UUID, dict] = {}
    for project_id, day, clicks in rows:
        by_project.setdefault(project_id, {})[day] = clicks
    return {
        project_id: [
            by_project.get(project_id, {}).get(last - timedelta(days=CLICKS_SERIES_DAYS - 1 - i))
            for i in range(CLICKS_SERIES_DAYS)
        ]
        for project_id, last in newest.items()
    }


@router.get("/traffic/overview", response_model=list[TrafficOverviewItem])
async def traffic_overview(
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_async_session)
) -> list[dict]:
    result = await session.execute(
        select(Project)
        .where(Project.is_demo == user.is_demo, Project.is_pipeline.is_(True))
        .order_by(Project.name)
        .options(selectinload(Project.traffic_snapshots))
    )
    projects = list(result.scalars().all())
    collected = dict(
        (
            await session.execute(
                select(TrafficDaily.project_id, func.max(TrafficDaily.updated_at)).group_by(TrafficDaily.project_id)
            )
        ).all()
    )
    series = await _clicks_series(session, [p.id for p in projects])
    items = []
    for project in projects:
        latest: TrafficSnapshot | None = project.traffic_snapshots[0] if project.traffic_snapshots else None
        items.append(
            {
                "project_id": project.id,
                "slug": project.slug,
                "name": project.name,
                "url": project.url,
                "configured": bool(project.gsc_site_url or project.ga4_property_id) or bool(latest and latest.configured),
                "clicks": latest.clicks if latest else None,
                "impressions": latest.impressions if latest else None,
                "sessions": latest.sessions if latest else None,
                "alert_severity": latest.alert_severity if latest else None,
                "alert_messages": latest.alert_messages if latest else None,
                "last_collected_at": collected.get(project.id),
                "clicks_series": series.get(project.id, []),
            }
        )
    return items


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Project:
    _require_write_access(user)
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await session.commit()
    await session.refresh(project)
    return project


@router.post("/projects/{project_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    project_id: uuid.UUID,
    data: TaskCreate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Task:
    _require_write_access(user)
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    task = Task(project_id=project_id, **data.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: uuid.UUID,
    data: TaskUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Task:
    _require_write_access(user)
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    await session.commit()
    await session.refresh(task)
    return task
