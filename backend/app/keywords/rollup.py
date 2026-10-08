"""Weekly Search Console query rollups: the free seed and demand data for the keyword generator."""
import asyncio
import logging
import urllib.parse
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector.summary import GSC_LAG_DAYS
from app.indexing.jobs import _projects, _summarise
from app.models.indexing import GscQueryRollup, RollupRequest
from app.models.project import Project


logger = logging.getLogger("helm.keywords")

URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
ROW_LIMIT = 25000
MAX_PAGES = 20  # 500k rows per project per pull is far beyond what these sites produce
REFRESH_DAYS = 35
BACKFILL_DAYS = 120
UPSERT_CHUNK = 3000


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def fetch_gsc_query_rows(session, site_url: str, start: date, end: date) -> list[dict]:
    """Pages through searchAnalytics/query with dimensions query+page+date."""
    url = URL.format(site=urllib.parse.quote(site_url, safe=""))
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query", "page", "date"],
            "rowLimit": ROW_LIMIT,
            "startRow": page * ROW_LIMIT,
        }
        response = session.post(url, json=body, timeout=120)
        response.raise_for_status()
        batch = response.json().get("rows", [])
        rows.extend(batch)
        if len(batch) < ROW_LIMIT:
            break
    return rows


def aggregate_weekly(rows: list[dict]) -> list[dict]:
    """Daily rows to weekly (query, page) rows; position is impression-weighted so busy days dominate."""
    buckets: dict[tuple, list[float]] = defaultdict(lambda: [0, 0, 0.0])  # clicks, impressions, position*impr
    for row in rows:
        query, page, day = row["keys"]
        key = (week_start(date.fromisoformat(day)), query, page)
        impressions = int(row["impressions"])
        bucket = buckets[key]
        bucket[0] += int(row["clicks"])
        bucket[1] += impressions
        bucket[2] += float(row["position"]) * impressions
    return [
        {
            "week_start": week,
            "query": query,
            "page": page,
            "clicks": int(clicks),
            "impressions": int(impressions),
            "position_avg": round(weighted / impressions, 2) if impressions else 0.0,
        }
        for (week, query, page), (clicks, impressions, weighted) in buckets.items()
    ]


async def upsert_rollups(db: AsyncSession, project_id, rows: list[dict]) -> int:
    for i in range(0, len(rows), UPSERT_CHUNK):
        chunk = [{**r, "project_id": project_id} for r in rows[i : i + UPSERT_CHUNK]]
        statement = insert(GscQueryRollup).values(chunk)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["project_id", "week_start", "query", "page"],
                set_={c: statement.excluded[c] for c in ("clicks", "impressions", "position_avg")},
            )
        )
    await db.commit()
    return len(rows)


async def rollup_project(session_factory: Callable, google_session, project, today: date) -> dict:
    """Pulls and stores one project's weekly rollups and rebuilds its digest. Raises on failure."""
    end = today - timedelta(days=GSC_LAG_DAYS)
    async with session_factory() as db:
        has_rows = (
            await db.execute(select(func.count()).select_from(GscQueryRollup).where(GscQueryRollup.project_id == project.id))
        ).scalar_one()
        days = REFRESH_DAYS if has_rows else BACKFILL_DAYS
        # Start on a week boundary so the first (partial) week is re-aggregated from complete data.
        start = week_start(end - timedelta(days=days))
        raw = await asyncio.to_thread(fetch_gsc_query_rows, google_session, project.gsc_site_url, start, end)
        weekly = aggregate_weekly(raw)
        n = await upsert_rollups(db, project.id, weekly)
        # Imported here: digest builds on this module's week_start.
        from app.core.app_settings import get_setting
        from app.keywords.digest import build_digest, last_complete_week

        await build_digest(db, project.id, last_complete_week(today), await get_setting(db, "thin_word_threshold"))
    return {"status": "ok", "rows": n, "raw_rows": len(raw)}


async def run_gsc_query_rollup(session_factory: Callable, google_session, today: date | None = None) -> dict:
    today = today or date.today()
    detail: dict[str, dict] = {}
    for project in await _projects(session_factory, with_gsc=True):
        try:
            detail[project.slug] = await rollup_project(session_factory, google_session, project, today)
        except Exception as exc:  # noqa: BLE001
            logger.exception("query rollup failed for %s", project.slug)
            detail[project.slug] = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"[:300]]}
    return _summarise(detail, rows=sum(d.get("rows", 0) for d in detail.values()))


async def run_rollup_requests(session_factory: Callable, google_session, today: date | None = None, now: datetime | None = None) -> int:
    """Runs queued manual refreshes: one pull per project however many requests are waiting, then marks each
    request done or failed. Returns how many requests were closed."""
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        pending = list((await db.execute(select(RollupRequest).where(RollupRequest.done_at.is_(None)).order_by(RollupRequest.requested_at).limit(50))).scalars())
    by_project: dict = defaultdict(list)
    for request in pending:
        by_project[request.project_id].append(request.id)
    for project_id, request_ids in by_project.items():
        error = None
        try:
            async with session_factory() as db:
                project = await db.get(Project, project_id)
            if project is None or not project.gsc_site_url:
                raise ValueError("project has no Search Console property")
            await rollup_project(session_factory, google_session, project, today)
        except Exception as exc:  # noqa: BLE001 -- recorded on the request so the caller can see why
            logger.exception("manual rollup failed for project %s", project_id)
            error = f"{type(exc).__name__}: {exc}"[:300]
        async with session_factory() as db:
            for request_id in request_ids:
                row = await db.get(RollupRequest, request_id)
                row.done_at, row.error = now, error
            await db.commit()
    return len(pending)
