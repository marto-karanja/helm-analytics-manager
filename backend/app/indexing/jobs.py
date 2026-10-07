"""Scheduled indexing jobs: sitemap_walk, page_signals, url_inspection. Each returns a detail dict for collector_runs."""
import asyncio
import logging
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import INSPECTION_CEILING, effective_budget, get_setting
from app.core.config import settings
from app.indexing import inspection as inspection_api
from app.indexing import service
from app.indexing import signals as signals_mod
from app.indexing.sitemap import walk_sitemaps
from app.models.indexing import PageSignal, SitemapStatus, SitemapUrl, UrlInspection
from app.models.project import Project

logger = logging.getLogger("helm.indexing")

SITEMAP_LIST_URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/sitemaps"
MAX_SIGNALS_PER_RUN_PER_PROJECT = 300
SIGNAL_REFRESH_DAYS = 30
THIN_RENDER_FALLBACK_WORDS = 50  # a near-empty plain-HTTP page is probably JS-rendered


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def http_fetch(url: str) -> bytes | None:
    """Sitemap/robots fetch used by the walker: None for 404, raises for other failures."""
    response = requests.get(url, headers={"User-Agent": signals_mod.USER_AGENT}, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


async def _projects(session_factory: Callable, with_gsc: bool = False) -> list[Project]:
    async with session_factory() as db:
        result = await db.execute(
            select(Project).where(Project.is_demo.is_(False), Project.is_pipeline.is_(True)).order_by(Project.slug)
        )
        projects = [p for p in result.scalars() if p.url]
    return [p for p in projects if p.gsc_site_url] if with_gsc else projects


# ---------------------------------------------------------------- sitemap_walk


async def _store_urls(db: AsyncSession, project: Project, found: dict, now: datetime) -> tuple[int, int]:
    """Upserts what the walk found and marks everything else removed. Returns (added, removed)."""
    existing = {
        row.url: row
        for row in (await db.execute(select(SitemapUrl).where(SitemapUrl.project_id == project.id))).scalars()
    }
    added = sum(1 for url in found if url not in existing or existing[url].removed_at is not None)
    if found:
        statement = insert(SitemapUrl).values(
            [
                {
                    "project_id": project.id,
                    "url": url,
                    "source_sitemap": source,
                    "lastmod": lastmod,
                    "first_seen_at": now,
                    "last_seen_at": now,
                }
                for url, (source, lastmod) in found.items()
            ]
        )
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["project_id", "url"],
                set_={
                    "source_sitemap": statement.excluded.source_sitemap,
                    "lastmod": statement.excluded.lastmod,
                    "last_seen_at": now,
                    "removed_at": None,
                },
            )
        )
    gone = [url for url, row in existing.items() if url not in found and row.removed_at is None]
    if found and gone:  # an empty walk means the fetch failed, not that every page was deleted
        await db.execute(
            update(SitemapUrl).where(SitemapUrl.project_id == project.id, SitemapUrl.url.in_(gone)).values(removed_at=now)
        )
    await db.commit()
    return added, len(gone) if found else 0


def _parse_google_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _web_counts(sitemap: dict) -> tuple[int | None, int | None]:
    for content in sitemap.get("contents", []):
        if content.get("type") == "web":
            submitted, indexed = content.get("submitted"), content.get("indexed")
            return (int(submitted) if submitted is not None else None, int(indexed) if indexed is not None else None)
    return None, None


async def _store_sitemap_status(db: AsyncSession, project: Project, google_session) -> int:
    url = SITEMAP_LIST_URL.format(site=urllib.parse.quote(project.gsc_site_url, safe=""))
    response = await asyncio.to_thread(google_session.get, url, timeout=60)
    response.raise_for_status()
    entries = response.json().get("sitemap", [])
    for entry in entries:
        submitted, indexed = _web_counts(entry)
        values = {
            "project_id": project.id,
            "path": entry["path"],
            "last_submitted": _parse_google_time(entry.get("lastSubmitted")),
            "last_downloaded": _parse_google_time(entry.get("lastDownloaded")),
            "is_pending": bool(entry.get("isPending")),
            "errors": int(entry.get("errors", 0)),
            "warnings": int(entry.get("warnings", 0)),
            "submitted_urls": submitted,
            "indexed_urls": indexed,
            "fetched_at": func.now(),
        }
        statement = insert(SitemapStatus).values(values)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["project_id", "path"],
                set_={k: statement.excluded[k] for k in values if k not in {"project_id", "path"}},
            )
        )
    await db.commit()
    return len(entries)


async def run_sitemap_walk(
    session_factory: Callable, google_session=None, fetch: Callable | None = None, now: datetime | None = None
) -> dict:
    now = now or datetime.now(timezone.utc)
    fetch = fetch or http_fetch
    detail: dict[str, dict] = {}
    for project in await _projects(session_factory):
        entry: dict = {"status": "ok"}
        try:
            result = await asyncio.to_thread(walk_sitemaps, fetch, project.url)
            async with session_factory() as db:
                entry["added"], entry["removed"] = await _store_urls(db, project, result.urls, now)
                entry["urls"] = len(result.urls)
                entry["sitemaps"] = result.sitemaps_read
                if result.errors:
                    entry["errors"] = result.errors[:10]
                    entry["status"] = "error" if not result.urls else "partial"
                if google_session is not None and project.gsc_site_url:
                    try:
                        entry["sitemap_status_rows"] = await _store_sitemap_status(db, project, google_session)
                    except Exception as exc:  # noqa: BLE001 -- sitemap health is secondary to the URL list
                        await db.rollback()
                        entry.setdefault("errors", []).append(f"sitemaps.list: {_err(exc)}")
                        entry["status"] = "partial" if entry["status"] == "ok" else entry["status"]
                thin = await get_setting(db, "thin_word_threshold")
                await service.record_snapshot(db, project.id, thin)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sitemap walk failed for %s", project.slug)
            entry = {"status": "error", "errors": [_err(exc)]}
        detail[project.slug] = entry
    return _summarise(detail, rows=sum(d.get("urls", 0) for d in detail.values()))


# ---------------------------------------------------------------- page_signals


def _crawler_extract(url: str) -> str | None:
    if not (settings.crawler_url and settings.crawler_api_key):
        return None
    response = requests.post(
        settings.crawler_url.rstrip("/") + "/extract",
        json={"url": url},
        headers={"X-API-Key": settings.crawler_api_key},
        timeout=90,
    )
    response.raise_for_status()
    return response.json().get("html")


def build_signal(project_id, page: signals_mod.FetchedPage, crawler: Callable | None = None) -> PageSignal:
    crawler = crawler or _crawler_extract
    row = PageSignal(project_id=project_id, url=page.url, http_status=page.http_status, error=page.error)
    if page.html is None:
        return row
    parsed = signals_mod.parse_html(page.html, page.final_url or page.url)
    source = "http"
    if page.http_status == 200 and parsed.word_count < THIN_RENDER_FALLBACK_WORDS:
        try:
            rendered = crawler(page.url)
        except Exception as exc:  # noqa: BLE001 -- the plain-HTTP result still stands
            logger.info("crawler fallback failed for %s: %s", page.url, _err(exc))
            rendered = None
        if rendered:
            parsed, source = signals_mod.parse_html(rendered, page.final_url or page.url), "crawler"
    row.title, row.meta_description = parsed.title, parsed.meta_description
    row.word_count, row.h1_count, row.h2_count = parsed.word_count, parsed.h1_count, parsed.h2_count
    row.headings, row.internal_links = parsed.headings, parsed.internal_links
    row.canonical, row.content_hash, row.source = parsed.canonical, parsed.content_hash, source
    row.noindex = parsed.noindex or page.x_robots_noindex
    return row


async def _urls_needing_signals(db: AsyncSession, project: Project, now: datetime) -> list[str]:
    urls = await service.live_urls(db, project.id)
    latest = await service.latest_signals(db, project.id)
    stale_before = now - timedelta(days=SIGNAL_REFRESH_DAYS)
    never, changed, stale = [], [], []
    for u in urls:
        sig = latest.get(u.url)
        if sig is None:
            never.append(u.url)
        elif u.lastmod and u.lastmod > sig.fetched_at:
            changed.append(u.url)
        elif sig.fetched_at < stale_before:
            stale.append(u.url)
    return (never + changed + stale)[:MAX_SIGNALS_PER_RUN_PER_PROJECT]


async def run_page_signals(
    session_factory: Callable, fetch: Callable | None = None, now: datetime | None = None
) -> dict:
    now = now or datetime.now(timezone.utc)
    fetch = fetch or signals_mod.fetch_page
    detail: dict[str, dict] = {}
    for project in await _projects(session_factory):
        try:
            async with session_factory() as db:
                todo = await _urls_needing_signals(db, project, now)
                fetched = failed = 0
                for url in todo:
                    page = await asyncio.to_thread(fetch, url)
                    row = build_signal(project.id, page)
                    db.add(row)
                    if row.error or (row.http_status or 0) >= 400:
                        failed += 1
                    fetched += 1
                    if fetched % 25 == 0:
                        await db.commit()
                await db.commit()
                thin = await get_setting(db, "thin_word_threshold")
                await service.record_snapshot(db, project.id, thin)
            detail[project.slug] = {"status": "ok", "fetched": fetched, "fetch_failures": failed}
        except Exception as exc:  # noqa: BLE001
            logger.exception("page signals failed for %s", project.slug)
            detail[project.slug] = {"status": "error", "errors": [_err(exc)]}
    return _summarise(detail, rows=sum(d.get("fetched", 0) for d in detail.values()))


# ---------------------------------------------------------------- url_inspection


async def inspections_today(db: AsyncSession, now: datetime) -> dict:
    """Inspections already spent today (UTC), overall and per project, so manual and scheduled runs share one budget."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await db.execute(
            select(UrlInspection.project_id, func.count())
            .where(UrlInspection.inspected_at >= start)
            .group_by(UrlInspection.project_id)
        )
    ).all()
    return {project_id: n for project_id, n in rows}


async def inspection_queue(db: AsyncSession, project: Project, now: datetime) -> list[str]:
    """Never inspected, then URLs whose page changed since their last inspection, then oldest inspection.

    Changed pages rank above merely old ones: in the literal order "never, oldest, changed" every
    inspected URL is already in the "oldest" tier, so the "changed" tier could never be reached.
    """
    urls = await service.live_urls(db, project.id)
    inspections = await service.latest_inspections(db, project.id)
    signals = await service.latest_signals(db, project.id)
    min_age = now - timedelta(days=inspection_api.MIN_REINSPECT_DAYS)
    never, changed, oldest = [], [], []
    for u in urls:
        ins = inspections.get(u.url)
        if ins is None:
            never.append(u.url)
            continue
        sig = signals.get(u.url)
        content_changed = bool(sig and sig.fetched_at > ins.inspected_at and sig.content_hash)
        if content_changed:
            changed.append((ins.inspected_at, u.url))
        elif ins.inspected_at < min_age:
            oldest.append((ins.inspected_at, u.url))
    return never + [u for _, u in sorted(changed)] + [u for _, u in sorted(oldest)]


async def store_inspection(db: AsyncSession, project: Project, url: str, google_session, now: datetime | None = None) -> UrlInspection:
    parsed = await asyncio.to_thread(inspection_api.inspect_url, google_session, project.gsc_site_url, url)
    row = UrlInspection(project_id=project.id, url=url, **parsed)
    if now is not None:
        row.inspected_at = now  # the job clock, so the daily budget and re-inspect ordering agree with it
    db.add(row)
    await db.commit()
    return row


async def run_url_inspection(session_factory: Callable, google_session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    projects = await _projects(session_factory, with_gsc=True)
    async with session_factory() as db:
        budget = effective_budget(await get_setting(db, "inspection_budget"))
        split = await get_setting(db, "inspection_budget_split")
        spent_by_project = await inspections_today(db, now)
        queues = {p.slug: await inspection_queue(db, p, now) for p in projects}
    remaining = max(0, budget - sum(spent_by_project.values()))
    by_slug = {p.slug: p for p in projects}
    caps = {}
    for slug, project in by_slug.items():
        spent = spent_by_project.get(project.id, 0)
        caps[slug] = max(0, min(split.get(slug, inspection_api.PER_PROPERTY_DAILY_QUOTA), inspection_api.PER_PROPERTY_DAILY_QUOTA) - spent)
    chosen = inspection_api.allocate(queues, remaining, caps)

    detail: dict[str, dict] = {slug: {"status": "ok", "inspected": 0, "failures": 0} for slug in queues}
    for slug, url in chosen:
        project = by_slug[slug]
        try:
            async with session_factory() as db:
                await store_inspection(db, project, url, google_session, now)
            detail[slug]["inspected"] += 1
        except Exception as exc:  # noqa: BLE001 -- a bad URL or quota error must not stop the other projects
            detail[slug]["failures"] += 1
            detail[slug]["last_error"] = _err(exc)
            if "HTTP 429" in str(exc):  # quota exhausted: stop spending, retry tomorrow
                break
    for slug, entry in detail.items():
        if entry["failures"] and not entry["inspected"]:
            entry["status"] = "error"
        elif entry["failures"]:
            entry["status"] = "partial"
        if entry["inspected"]:
            async with session_factory() as db:
                thin = await get_setting(db, "thin_word_threshold")
                await service.record_snapshot(db, by_slug[slug].id, thin)
    detail["_budget"] = {"budget": budget, "spent_before": sum(spent_by_project.values()), "chosen": len(chosen)}
    return _summarise({k: v for k, v in detail.items() if k != "_budget"}, rows=len(chosen), extra={"_budget": detail["_budget"]})


def _summarise(detail: dict[str, dict], rows: int, extra: dict | None = None) -> dict:
    statuses = [d["status"] for d in detail.values()]
    if not statuses:
        status = "skipped"
    elif all(s == "error" for s in statuses):
        status = "error"
    elif any(s in {"error", "partial"} for s in statuses):
        status = "partial"
    else:
        status = "ok"
    return {"status": status, "rows": rows, "detail": {**detail, **(extra or {})}}


# ---------------------------------------------------------------- manual requests


async def run_inspect_requests(session_factory: Callable, google_session, now: datetime | None = None) -> int:
    """Processes queued "Inspect now" requests. They were checked against the budget when queued, so they run
    even if a scheduled run has since used the rest of the day; the hard ceiling is enforced here too."""
    from app.models.indexing import InspectRequest

    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        pending = list(
            (
                await db.execute(
                    select(InspectRequest).where(InspectRequest.done_at.is_(None)).order_by(InspectRequest.requested_at).limit(50)
                )
            ).scalars()
        )
        spent = sum((await inspections_today(db, now)).values())
    done = 0
    for request in pending:
        async with session_factory() as db:
            row = await db.get(InspectRequest, request.id)
            project = await db.get(Project, request.project_id)
            try:
                if spent >= INSPECTION_CEILING:
                    raise inspection_api.InspectionError("daily ceiling reached")
                if project is None or not project.gsc_site_url:
                    raise inspection_api.InspectionError("project has no Search Console property")
                await store_inspection(db, project, request.url, google_session, now)
                spent += 1
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                row = await db.get(InspectRequest, request.id)
                row.error = _err(exc)
            row.done_at = datetime.now(timezone.utc)
            await db.commit()
            done += 1
    return done


