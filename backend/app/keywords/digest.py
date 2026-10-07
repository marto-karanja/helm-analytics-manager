"""Weekly digest: a frozen per-project snapshot (traffic delta, indexing counts, top queries, pending work)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing import service as indexing_service
from app.keywords import queries
from app.keywords.rollup import week_start
from app.models.indexing import GscQueryRollup, KeywordCandidate, WeeklyDigest
from app.models.project import TrafficDaily

TOP_QUERIES = 10


def _delta(current: int, previous: int) -> float | None:
    return round(100 * (current - previous) / previous, 1) if previous else None


async def _traffic_week(db: AsyncSession, project_id: uuid.UUID, start: date) -> dict:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(TrafficDaily.clicks), 0),
                func.coalesce(func.sum(TrafficDaily.impressions), 0),
                func.coalesce(func.sum(TrafficDaily.sessions), 0),
            ).where(
                TrafficDaily.project_id == project_id,
                TrafficDaily.metric_date >= start,
                TrafficDaily.metric_date < start + timedelta(days=7),
            )
        )
    ).one()
    return {"clicks": int(row[0]), "impressions": int(row[1]), "sessions": int(row[2])}


async def build_digest(db: AsyncSession, project_id: uuid.UUID, week: date, thin_words: int) -> dict:
    """Builds and stores the digest for the week starting `week` (a Monday)."""
    this_week = await _traffic_week(db, project_id, week)
    last_week = await _traffic_week(db, project_id, week - timedelta(days=7))

    top = (
        await db.execute(
            select(
                GscQueryRollup.query,
                func.sum(GscQueryRollup.clicks).label("clicks"),
                func.sum(GscQueryRollup.impressions).label("impressions"),
            )
            .where(GscQueryRollup.project_id == project_id, GscQueryRollup.week_start == week)
            .group_by(GscQueryRollup.query)
            .order_by(func.sum(GscQueryRollup.impressions).desc())
            .limit(TOP_QUERIES)
        )
    ).all()

    counts = indexing_service.count_issues(await indexing_service.url_statuses(db, project_id, thin_words))
    stats = await queries.query_stats(db, project_id, today=week + timedelta(days=7))
    pending = (
        await db.execute(
            select(func.count()).select_from(KeywordCandidate).where(
                KeywordCandidate.project_id == project_id, KeywordCandidate.status == "proposed"
            )
        )
    ).scalar_one()

    payload = {
        "week_start": week.isoformat(),
        "traffic": {
            **this_week,
            "previous": last_week,
            "clicks_change_pct": _delta(this_week["clicks"], last_week["clicks"]),
            "impressions_change_pct": _delta(this_week["impressions"], last_week["impressions"]),
        },
        "indexing": {"counts": counts, "indexed_percent": indexing_service.indexed_percent(counts)},
        "top_queries": [{"query": q, "clicks": int(c), "impressions": int(i)} for q, c, i in top],
        "striking_distance": len(queries.striking_distance(stats)),
        "pending_keyword_candidates": int(pending),
    }
    statement = insert(WeeklyDigest).values(project_id=project_id, week_start=week, payload=payload)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["project_id", "week_start"], set_={"payload": statement.excluded.payload}
        )
    )
    await db.commit()
    return payload


def last_complete_week(today: date) -> date:
    return week_start(today) - timedelta(days=7)
