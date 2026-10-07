import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.users import current_active_user
from app.db.session import get_async_session
from app.models.project import Project
from app.models.user import User


def require_owner(user: User = Depends(current_active_user)) -> User:
    """The owner is any real (non-demo) account; registration is disabled, so that is one person."""
    if user.is_demo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Demo account is read-only")
    return user


async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> Project:
    """The project, scoped so the demo account only ever sees demo projects and vice versa."""
    project = (
        await session.execute(select(Project).where(Project.id == project_id, Project.is_demo == user.is_demo))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project
