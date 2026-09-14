import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.users import UserManager, auth_backend, fastapi_users, get_user_manager
from app.db.session import get_async_session
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter()

router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])

DEMO_EMAIL = "demo@helm.billtoolbox.com"


@router.post("/auth/demo-login", tags=["auth"])
async def demo_login(
    session: AsyncSession = Depends(get_async_session),
    user_manager: UserManager = Depends(get_user_manager),
):
    """No credentials needed -- gets or creates the single shared demo
    account and issues it a normal access token, same shape as /auth/login."""
    result = await session.execute(select(User).where(User.email == DEMO_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        user = await user_manager.create(
            UserCreate(email=DEMO_EMAIL, password=secrets.token_urlsafe(32), is_demo=True)
        )
    strategy = auth_backend.get_strategy()
    return await auth_backend.login(strategy, user)
