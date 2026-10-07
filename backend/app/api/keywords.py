
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import get_project, require_owner
from app.core.app_settings import get_setting
from app.core.config import settings
from app.core.users import current_active_user
from app.db.session import get_async_session
from app.keywords import export as export_mod
from app.keywords import generator, queries
from app.keywords.launch import launch_run
from app.keywords import llm as llm_mod
from app.models.indexing import KeywordCandidate, KeywordRun
from app.models.project import Project
from app.models.user import User



router = APIRouter(dependencies=[Depends(current_active_user)])

Status = Literal["proposed", "accepted", "rejected"]


class StatusBody(BaseModel):
    status: Status


class BulkBody(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    status: Status


def candidate_dict(c: KeywordCandidate) -> dict[str, Any]:
    return {
        "id": c.id,
        "keyword": c.keyword,
        "cluster_id": c.cluster_id,
        "cluster_label": c.cluster_label,
        "intent": c.intent,
        "volume": c.volume,
        "volume_is_bucket": c.volume_is_bucket,
        "competition": c.competition,
        "impressions_proxy": c.impressions_proxy,
        "position_avg": c.position_avg,
        "demand_est": c.demand_est,
        "demand_source": c.demand_source,
        "gap": c.gap,
        "score": c.score,
        "source": c.source,
        "status": c.status,
        "target_url": c.target_url,
        "decided_at": c.decided_at,
    }


def run_dict(r: KeywordRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "status": r.status,
        "model": r.model,
        "prompt_version": r.prompt_version,
        "source_counts": r.source_counts,
        "error": r.error,
        "cost_usd": r.cost_usd,
    }


@router.get("/projects/{project_id}/keywords")
async def list_keywords(
    status_filter: Status | None = Query(None, alias="status"),
    limit: int = Query(200, ge=1, le=1000),
    project: Project = Depends(get_project),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    stmt = select(KeywordCandidate).where(KeywordCandidate.project_id == project.id)
    if status_filter:
        stmt = stmt.where(KeywordCandidate.status == status_filter)
    rows = (await session.execute(stmt.order_by(KeywordCandidate.score.desc(), KeywordCandidate.keyword).limit(limit))).scalars().all()
    counts = dict(
        (
            await session.execute(
                select(KeywordCandidate.status, func.count()).where(KeywordCandidate.project_id == project.id).group_by(KeywordCandidate.status)
            )
        ).all()
    )
    runs = (
        await session.execute(select(KeywordRun).where(KeywordRun.project_id == project.id).order_by(KeywordRun.started_at.desc()).limit(5))
    ).scalars().all()
    return {
        "candidates": [candidate_dict(c) for c in rows],
        "counts": {s: counts.get(s, 0) for s in ("proposed", "accepted", "rejected", "written")},
        "runs": [run_dict(r) for r in runs],
        "volume_source": await get_setting(session, "volume_source"),
        "llm_configured": bool(settings.anthropic_api_key),
    }



@router.post("/projects/{project_id}/keywords/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_keyword_run(
    project: Project = Depends(get_project),
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="HELM_ANTHROPIC_API_KEY is not configured")
    try:
        run = await launch_run(session, project)
    except llm_mod.DailyCapReached as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except generator.GeneratorError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return run_dict(run)


async def _decide(session: AsyncSession, candidate: KeywordCandidate, new_status: str) -> None:
    candidate.status = new_status
    candidate.decided_at = None if new_status == "proposed" else datetime.now(timezone.utc)


@router.patch("/keywords/{candidate_id}")
async def set_candidate_status(
    candidate_id: uuid.UUID,
    body: StatusBody,
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    candidate = await session.get(KeywordCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    project = await session.get(Project, candidate.project_id)
    if project is None or project.is_demo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    if candidate.status == "written" and body.status != "written":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already exported to the queue file")
    await _decide(session, candidate, body.status)
    await session.commit()
    return candidate_dict(candidate)


@router.post("/projects/{project_id}/keywords/bulk")
async def bulk_set_status(
    body: BulkBody,
    project: Project = Depends(get_project),
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, int]:
    rows = (
        await session.execute(
            select(KeywordCandidate).where(
                KeywordCandidate.project_id == project.id,
                KeywordCandidate.id.in_(body.ids),
                KeywordCandidate.status != "written",
            )
        )
    ).scalars().all()
    for row in rows:
        await _decide(session, row, body.status)
    await session.commit()
    return {"updated": len(rows)}


@router.post("/projects/{project_id}/keywords/export")
async def export_keyword_queue(
    project: Project = Depends(get_project),
    user: User = Depends(require_owner),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await export_mod.export_queue(session, project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"count": result["count"], "path": result["path"], "queue": result["payload"]}


@router.get("/projects/{project_id}/keywords/striking-distance")
async def striking_distance_queries(
    project: Project = Depends(get_project), session: AsyncSession = Depends(get_async_session)
) -> list[dict[str, Any]]:
    stats = queries.striking_distance(await queries.query_stats(session, project.id))
    return [
        {"query": s.query, "page": s.top_page, "impressions": s.impressions, "clicks": s.clicks, "position": s.position}
        for s in stats
    ]
