"""Owner settings, MCP token management, and the token-authenticated keyword queue pull for pipelines."""
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import require_owner
from app.core import app_settings, mcp_tokens
from app.core.users import current_active_user
from app.db.session import get_async_session
from app.keywords import export as export_mod
from app.models.indexing import McpCall, McpToken
from app.models.project import Project
from app.models.user import User

router = APIRouter()


class SettingBody(BaseModel):
    value: Any


class TokenBody(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    scope: Literal["read", "write"] = "read"


@router.get("/settings")
async def read_settings(
    user: User = Depends(current_active_user), session: AsyncSession = Depends(get_async_session)
) -> dict[str, Any]:
    values = await app_settings.get_all_settings(session)
    return {
        "values": values,
        "descriptions": {key: spec.description for key, spec in app_settings.SPECS.items()},
        "limits": {"inspection_ceiling": app_settings.INSPECTION_CEILING, "volume_sources": list(app_settings.VOLUME_SOURCES)},
        "editable": not user.is_demo,
    }


@router.put("/settings/{key}")
async def write_setting(
    key: str,
    body: SettingBody,
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        value = await app_settings.put_setting(session, key, body.value, user.email)
    except app_settings.SettingError as exc:
        raise HTTPException(status_code=422, detail=f"{key}: {exc}") from exc
    return {"key": key, "value": value}


def _token_dict(t: McpToken) -> dict[str, Any]:
    return {
        "id": t.id,
        "label": t.label,
        "scope": t.scope,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "revoked_at": t.revoked_at,
    }


@router.get("/mcp-tokens")
async def list_tokens(user: User = Depends(require_owner), session: AsyncSession = Depends(get_async_session)) -> list[dict]:
    rows = (await session.execute(select(McpToken).order_by(McpToken.created_at.desc()))).scalars().all()
    return [_token_dict(t) for t in rows]


@router.post("/mcp-tokens", status_code=status.HTTP_201_CREATED)
async def create_token(
    body: TokenBody, user: User = Depends(require_owner), session: AsyncSession = Depends(get_async_session)
) -> dict[str, Any]:
    row, raw = await mcp_tokens.create_token(session, body.label, body.scope)
    # The only time the plaintext is ever returned; only its hash is stored.
    return {**_token_dict(row), "token": raw}


@router.delete("/mcp-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID, user: User = Depends(require_owner), session: AsyncSession = Depends(get_async_session)
) -> None:
    row = await session.get(McpToken, token_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()


@router.get("/mcp-calls")
async def recent_calls(user: User = Depends(require_owner), session: AsyncSession = Depends(get_async_session)) -> list[dict]:
    rows = (await session.execute(select(McpCall).order_by(McpCall.created_at.desc()).limit(100))).scalars().all()
    return [
        {"created_at": c.created_at, "token": c.token_label, "tool": c.tool, "status": c.status, "args_hash": c.args_hash[:12]}
        for c in rows
    ]


@router.get("/keyword-queue/{slug}", tags=["pipelines"])
async def pull_keyword_queue(
    slug: str,
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """For publish pipelines: the accepted keywords for one site, with a read-scope MCP token as the bearer."""
    scheme, _, raw = authorization.partition(" ")
    token = await mcp_tokens.verify_token(session, raw) if scheme.lower() == "bearer" else None
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    project = (
        await session.execute(select(Project).where(Project.slug == slug, Project.is_demo.is_(False)))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return export_mod.queue_payload(project, await export_mod.queue_rows(session, project.id))
