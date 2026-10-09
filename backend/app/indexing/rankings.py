"""Per-page search rankings from the weekly (query, page) rollups.

A page has no single position in Search Console: each query has its own average. A page's position here is the
impression-weighted mean across its queries, so the queries people actually see it for dominate. Pure functions
over rollup rows, plus one async loader, shared by the REST API and the MCP tools."""
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_setting
from app.indexing import service
from app.models.indexing import GscQueryRollup, RollupRequest
from app.models.project import CollectorRun, Project

MAX_WEEKS = 12
MAX_PAGES = 500
TOP_QUERIES = 3
MAX_QUERIES_FOR_ONE_PAGE = 50


def normalise_url(url: str) -> str:
    """Join key between Search Console page URLs and sitemap URLs: scheme, www, query string, fragment and
    trailing slash are ignored."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def _weighted(rows: list[dict]) -> float | None:
    impressions = sum(r["impressions"] for r in rows)
    if not impressions:
        return None
    return round(sum(r["position_avg"] * r["impressions"] for r in rows) / impressions, 1)


def _by_page(rows: list[dict]) -> dict[str, list[dict]]:
    pages: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        pages[row["page"]].append(row)
    return pages


def _merge_queries(rows: list[dict]) -> list[dict]:
    """One row per query over the window (the same query appears once per week)."""
    merged: dict[str, dict] = {}
    for r in rows:
        m = merged.setdefault(r["query"], {"query": r["query"], "clicks": 0, "impressions": 0, "weighted": 0.0})
        m["clicks"] += r["clicks"]
        m["impressions"] += r["impressions"]
        m["weighted"] += r["position_avg"] * r["impressions"]
    out = [
        {
            "query": m["query"],
            "position": round(m["weighted"] / m["impressions"], 1) if m["impressions"] else None,
            "clicks": m["clicks"],
            "impressions": m["impressions"],
        }
        for m in merged.values()
    ]
    return sorted(out, key=lambda q: (-q["impressions"], q["query"]))


def build_rankings(
    current: list[dict],
    prior: list[dict],
    indexing_by_url: dict[str, dict],
    min_impressions: int = 10,
    limit: int = 100,
    only_url: str | None = None,
) -> dict:
    """`current` and `prior` are rollup rows for two equal consecutive windows. Position change is positive when
    the page moved up (prior minus current), so "+2.0" always reads as an improvement."""
    prior_by_page = {normalise_url(page): rows for page, rows in _by_page(prior).items()}
    pages = []
    for page, rows in _by_page(current).items():
        if only_url is not None and normalise_url(page) != normalise_url(only_url):
            continue
        impressions = sum(r["impressions"] for r in rows)
        if impressions < min_impressions and only_url is None:
            continue
        clicks = sum(r["clicks"] for r in rows)
        position = _weighted(rows)
        before = _weighted(prior_by_page.get(normalise_url(page), []))
        queries = _merge_queries(rows)
        state = indexing_by_url.get(normalise_url(page))
        pages.append(
            {
                "url": page,
                "position": position,
                "position_prior": before,
                "position_change": round(before - position, 1) if before is not None and position is not None else None,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": round(clicks / impressions, 4) if impressions else None,
                "query_count": len(queries),
                "top_queries": queries[: MAX_QUERIES_FOR_ONE_PAGE if only_url else TOP_QUERIES],
                "indexing": state["issue"] if state else None,
                "coverage_state": state["coverage_state"] if state else None,
            }
        )
    pages.sort(key=lambda p: (-p["impressions"], p["url"]))
    return {"total_pages": len(pages), "returned": min(limit, len(pages)), "pages": pages[:limit]}


async def _window_rows(db: AsyncSession, project_id, first: date, last: date) -> list[dict]:
    result = await db.execute(
        select(GscQueryRollup).where(
            GscQueryRollup.project_id == project_id, GscQueryRollup.week_start >= first, GscQueryRollup.week_start <= last
        )
    )
    return [
        {"page": r.page, "query": r.query, "clicks": r.clicks, "impressions": r.impressions, "position_avg": r.position_avg}
        for r in result.scalars()
    ]


async def refresh_state(db: AsyncSession, project: Project) -> dict:
    """When the data was last refreshed and whether a manual refresh is waiting, so a caller knows how fresh it is."""
    last_run = (
        await db.execute(
            select(func.max(CollectorRun.finished_at)).where(CollectorRun.kind == "gsc_query_rollup", CollectorRun.status.in_(("ok", "partial")))
        )
    ).scalar_one()
    last_manual = (
        await db.execute(
            select(func.max(RollupRequest.done_at)).where(RollupRequest.project_id == project.id, RollupRequest.error.is_(None))
        )
    ).scalar_one()
    pending = (
        await db.execute(select(func.count()).select_from(RollupRequest).where(RollupRequest.project_id == project.id, RollupRequest.done_at.is_(None)))
    ).scalar_one()
    newest = max((t for t in (last_run, last_manual) if t is not None), default=None)
    return {"last_refreshed_at": newest, "last_weekly_run_at": last_run, "last_manual_refresh_at": last_manual, "refresh_pending": pending > 0}


async def page_rankings(
    db: AsyncSession,
    project: Project,
    weeks: int = 4,
    min_impressions: int = 10,
    limit: int = 100,
    url: str | None = None,
    as_of: date | None = None,
) -> dict:
    """`as_of` anchors the window at the latest week that had fully ended by that date, so a past report never
    includes data pulled afterwards. Without it the window ends at the newest week stored."""
    weeks = max(1, min(weeks, MAX_WEEKS))
    limit = max(1, min(limit, MAX_PAGES))
    state = await refresh_state(db, project)
    newest = select(func.max(GscQueryRollup.week_start)).where(GscQueryRollup.project_id == project.id)
    if as_of is not None:
        newest = newest.where(GscQueryRollup.week_start <= as_of - timedelta(days=6))
    latest = (await db.execute(newest)).scalar_one()
    if latest is None:
        return {
            "project": project.slug,
            "note": "No query data collected yet. Request a refresh (POST rankings/refresh, or the refresh_rankings tool) or wait for the weekly run.",
            **state,
            "pages": [],
        }
    first = latest - timedelta(weeks=weeks - 1)
    current = await _window_rows(db, project.id, first, latest)
    prior = await _window_rows(db, project.id, first - timedelta(weeks=weeks), first - timedelta(weeks=1))
    thin = await get_setting(db, "thin_word_threshold")
    if as_of is None:
        statuses = await service.url_statuses(db, project.id, thin)
    else:
        statuses, _ = await service.status_as_of(db, project.id, thin, service.end_of_day(as_of))
    indexing = {normalise_url(r["url"]): r for r in statuses}
    result = build_rankings(current, prior, indexing, min_impressions, limit, url)
    return {
        "project": project.slug,
        "as_of": as_of,
        "window": {"weeks": weeks, "first_week_start": first, "latest_week_start": latest},
        "position_note": "Impression-weighted mean over the page's queries; lower is better. position_change is positive when the page moved up. The latest week may be partial and Search Console data trails by about 3 days.",
        **state,
        **result,
    }
