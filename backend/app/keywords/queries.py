"""Query-level reads over `gsc_query_rollups`: the seed list, the demand lookup and striking distance."""
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.keywords.rollup import week_start
from app.keywords.scoring import estimate_monthly_searches, is_striking_distance, normalise_keyword
from app.models.indexing import GscQueryRollup

DEFAULT_WEEKS = 4


@dataclass
class QueryStat:
    query: str
    impressions: int
    clicks: int
    position: float  # impression-weighted average over the window
    top_page: str | None  # the page with the most impressions for this query
    pages: int  # how many distinct pages are shown for it (more than one hints at cannibalization)

    @property
    def estimated_monthly_searches(self) -> float:
        return estimate_monthly_searches(self.impressions, self.position)

    @property
    def striking(self) -> bool:
        return is_striking_distance(self.position, self.impressions)


async def query_stats(
    db: AsyncSession, project_id: uuid.UUID, weeks: int = DEFAULT_WEEKS, today: date | None = None
) -> list[QueryStat]:
    """Aggregates the last `weeks` complete weeks. The current partial week is excluded so windows are comparable."""
    today = today or date.today()
    end = week_start(today)  # exclusive: the week that has not finished
    start = end - timedelta(weeks=weeks)
    rows = (
        await db.execute(
            select(
                GscQueryRollup.query,
                GscQueryRollup.page,
                func.sum(GscQueryRollup.impressions),
                func.sum(GscQueryRollup.clicks),
                func.sum(GscQueryRollup.position_avg * GscQueryRollup.impressions),
            )
            .where(GscQueryRollup.project_id == project_id, GscQueryRollup.week_start >= start, GscQueryRollup.week_start < end)
            .group_by(GscQueryRollup.query, GscQueryRollup.page)
        )
    ).all()
    per_query: dict[str, list] = defaultdict(list)
    for query, page, impressions, clicks, weighted in rows:
        per_query[query].append((page, int(impressions or 0), int(clicks or 0), float(weighted or 0.0)))
    stats = []
    for query, entries in per_query.items():
        impressions = sum(e[1] for e in entries)
        if impressions <= 0:
            continue
        stats.append(
            QueryStat(
                query=query,
                impressions=impressions,
                clicks=sum(e[2] for e in entries),
                position=round(sum(e[3] for e in entries) / impressions, 2),
                top_page=max(entries, key=lambda e: e[1])[0],
                pages=len(entries),
            )
        )
    return sorted(stats, key=lambda s: -s.impressions)


def by_normalised_query(stats: list[QueryStat]) -> dict[str, QueryStat]:
    """Lookup keyed on the normalised keyword; case variants Search Console reports separately are merged."""
    merged: dict[str, QueryStat] = {}
    for s in stats:
        key = normalise_keyword(s.query)
        if key not in merged:
            merged[key] = s
        else:
            other = merged[key]
            total = other.impressions + s.impressions
            merged[key] = QueryStat(
                query=other.query,
                impressions=total,
                clicks=other.clicks + s.clicks,
                position=round((other.position * other.impressions + s.position * s.impressions) / total, 2),
                top_page=other.top_page if other.impressions >= s.impressions else s.top_page,
                pages=max(other.pages, s.pages),
            )
    return merged


def striking_distance(stats: list[QueryStat]) -> list[QueryStat]:
    return sorted((s for s in stats if s.striking), key=lambda s: -s.impressions)


def cannibalised(stats: list[QueryStat], min_impressions: int = 20) -> list[QueryStat]:
    return sorted((s for s in stats if s.pages > 1 and s.impressions >= min_impressions), key=lambda s: -s.impressions)
