import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.users import current_active_user
from app.db.session import get_async_session
from app.models.project import Project, Task
from app.models.user import User
from app.schemas.project import (
    ProjectDetailRead,
    ProjectRead,
    ProjectUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TaskWithProjectRead,
)

router = APIRouter(dependencies=[Depends(current_active_user)])

SNAPSHOT_HISTORY_LIMIT = 30


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
    return project


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
