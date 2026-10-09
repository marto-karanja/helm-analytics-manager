"""The first and last date each report can answer for, from what is actually stored. A date outside these bounds
must come back as an explicit "history begins on ..." and never as an empty table that looks like zeros."""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing import GscQueryRollup, KeywordCandidate, SitemapUrl, WeeklyDigest
from app.models.project import TrafficDaily, TrafficSnapshot
from app.reports.catalog import BY_NAME


def _day(value: datetime | date | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


async def _min(db: AsyncSession, column, project_ids: list[uuid.UUID], project_column=None):
    stmt = select(func.min(column)).where((project_column if project_column is not None else column.class_.project_id).in_(project_ids))
    return (await db.execute(stmt)).scalar_one()


async def bounds(db: AsyncSession, name: str, project_ids: list[uuid.UUID], today: date) -> tuple[date | None, date | None]:
    """(first, last) as-of date the report can answer for the given projects. `last` is today except for traffic,
    which ends at the newest day collected."""
    if not project_ids:
        return None, None
    if name in ("indexing", "non-indexed", "urls"):
        return _day(await _min(db, SitemapUrl.first_seen_at, project_ids)), today
    if name == "rankings":
        first = await _min(db, GscQueryRollup.week_start, project_ids)
        return (first + timedelta(days=6) if first else None), today  # a week counts once it has fully ended
    if name in ("striking-distance", "cannibalisation"):
        first = await _min(db, GscQueryRollup.week_start, project_ids)
        return (first + timedelta(days=7) if first else None), today  # needs one complete week before the date
    if name == "digest":
        first = await _min(db, WeeklyDigest.week_start, project_ids)
        return (first + timedelta(days=6) if first else None), today
    if name == "traffic":
        first = await _min(db, TrafficDaily.metric_date, project_ids)
        last = (await db.execute(select(func.max(TrafficDaily.metric_date)).where(TrafficDaily.project_id.in_(project_ids)))).scalar_one()
        return first, last
    if name == "alerts":
        return _day(await _min(db, TrafficSnapshot.synced_at, project_ids)), today
    if name == "keywords":
        return _day(await _min(db, KeywordCandidate.created_at, project_ids)), today
    raise KeyError(name)


def out_of_range_note(name: str, as_of: date, first: date | None, last: date | None) -> str | None:
    """None when the date is answerable."""
    label = BY_NAME[name].label
    if first is None:
        return f"{label}: nothing has been collected yet."
    if as_of < first:
        return f"{label} history begins on {first.isoformat()}; there is nothing recorded for {as_of.isoformat()}."
    if last is not None and as_of > last and name == "traffic":
        return f"Traffic data ends on {last.isoformat()}; later days have not been collected yet."
    return None
