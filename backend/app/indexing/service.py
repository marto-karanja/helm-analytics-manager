"""Read side of indexing analysis: latest inspection + latest signals per sitemap URL, classified on demand.

Computed in Python, not a SQL view, because the thin-content threshold is an editable setting and
duplicate detection compares rows against each other.
"""
import uuid
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing import classify as rules
from app.models.indexing import IndexingSnapshot, PageSignal, SitemapUrl, UrlInspection, UrlStatusHistory


def end_of_day(day: date) -> datetime:
    """The last instant of a UTC calendar day: what "as of that date" means everywhere in Helm."""
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc) - timedelta(microseconds=1)


async def live_urls(db: AsyncSession, project_id: uuid.UUID, as_of: datetime | None = None) -> list[SitemapUrl]:
    """Sitemap URLs now, or those that were in the sitemap at `as_of`."""
    stmt = select(SitemapUrl).where(SitemapUrl.project_id == project_id)
    if as_of is None:
        stmt = stmt.where(SitemapUrl.removed_at.is_(None))
    else:
        stmt = stmt.where(SitemapUrl.first_seen_at <= as_of, or_(SitemapUrl.removed_at.is_(None), SitemapUrl.removed_at > as_of))
    return list((await db.execute(stmt.order_by(SitemapUrl.url))).scalars().all())


async def latest_inspections(db: AsyncSession, project_id: uuid.UUID, as_of: datetime | None = None) -> dict[str, UrlInspection]:
    stmt = select(UrlInspection).where(UrlInspection.project_id == project_id)
    if as_of is not None:
        stmt = stmt.where(UrlInspection.inspected_at <= as_of)
    result = await db.execute(stmt.distinct(UrlInspection.url).order_by(UrlInspection.url, UrlInspection.inspected_at.desc()))
    return {row.url: row for row in result.scalars()}


async def latest_signals(db: AsyncSession, project_id: uuid.UUID, as_of: datetime | None = None) -> dict[str, PageSignal]:
    stmt = select(PageSignal).where(PageSignal.project_id == project_id)
    if as_of is not None:
        stmt = stmt.where(PageSignal.fetched_at <= as_of)
    result = await db.execute(stmt.distinct(PageSignal.url).order_by(PageSignal.url, PageSignal.fetched_at.desc()))
    return {row.url: row for row in result.scalars()}


def make_facts(url: str, inspection: UrlInspection | None, signal: PageSignal | None) -> rules.UrlFacts:
    return rules.UrlFacts(
        url=url,
        http_status=signal.http_status if signal else None,
        fetch_error=signal.error if signal else None,
        noindex=bool(signal and signal.noindex),
        canonical=signal.canonical if signal else None,
        word_count=signal.word_count if signal else None,
        title=signal.title if signal else None,
        content_hash=signal.content_hash if signal else None,
        signals_fetched=signal is not None,
        inspected=inspection is not None,
        verdict=inspection.verdict if inspection else None,
        coverage_state=inspection.coverage_state if inspection else None,
        indexing_state=inspection.indexing_state if inspection else None,
        robots_txt_state=inspection.robots_txt_state if inspection else None,
        page_fetch_state=inspection.page_fetch_state if inspection else None,
    )


async def url_statuses(
    db: AsyncSession, project_id: uuid.UUID, thin_words: int, as_of: datetime | None = None
) -> list[dict[str, Any]]:
    """One row per live sitemap URL with its primary issue, newest signals and newest inspection.

    With `as_of`, the same computation over what existed at that instant, using today's rules and threshold
    ("reconstructed"). `status_as_of` prefers the exact stored history when it covers the date."""
    urls = await live_urls(db, project_id, as_of)
    inspections = await latest_inspections(db, project_id, as_of)
    signals = await latest_signals(db, project_id, as_of)
    facts = [make_facts(u.url, inspections.get(u.url), signals.get(u.url)) for u in urls]
    issues = rules.classify_all(facts, thin_words)
    rows = []
    for u in urls:
        ins, sig = inspections.get(u.url), signals.get(u.url)
        rows.append(
            {
                "id": u.id,
                "url": u.url,
                "lastmod": u.lastmod,
                "first_seen_at": u.first_seen_at,
                "issue": issues[u.url],
                "verdict": ins.verdict if ins else None,
                "coverage_state": ins.coverage_state if ins else None,
                "last_crawl_time": ins.last_crawl_time if ins else None,
                "inspected_at": ins.inspected_at if ins else None,
                "word_count": sig.word_count if sig else None,
                "title": sig.title if sig else None,
                "http_status": sig.http_status if sig else None,
            }
        )
    return rows


STATUS_FIELDS = ("issue", "verdict", "coverage_state", "last_crawl_time", "inspected_at", "word_count", "http_status", "title")


async def _latest_history(db: AsyncSession, project_id: uuid.UUID, as_of: datetime | None = None) -> dict[str, UrlStatusHistory]:
    stmt = select(UrlStatusHistory).where(UrlStatusHistory.project_id == project_id)
    if as_of is not None:
        stmt = stmt.where(UrlStatusHistory.valid_from <= as_of)
    result = await db.execute(stmt.distinct(UrlStatusHistory.url).order_by(UrlStatusHistory.url, UrlStatusHistory.valid_from.desc()))
    return {row.url: row for row in result.scalars()}


async def record_status_history(db: AsyncSession, project_id: uuid.UUID, thin_words: int, now: datetime | None = None) -> int:
    """Appends a history row for every URL whose classification or underlying facts changed since its last row,
    and a removal marker for URLs that left the sitemap. Returns how many rows were written. Append-only."""
    now = now or datetime.now(timezone.utc)
    rows = await url_statuses(db, project_id, thin_words)
    previous = await _latest_history(db, project_id)
    written = 0
    live = set()
    for r in rows:
        live.add(r["url"])
        last = previous.get(r["url"])
        if last is not None and last.issue is not None and all(getattr(last, f) == r[f] for f in STATUS_FIELDS):
            continue
        db.add(UrlStatusHistory(project_id=project_id, url=r["url"], valid_from=now, first_seen_at=r["first_seen_at"], **{f: r[f] for f in STATUS_FIELDS}))
        written += 1
    for url, last in previous.items():
        if url not in live and last.issue is not None:
            db.add(UrlStatusHistory(project_id=project_id, url=url, valid_from=now, issue=None, first_seen_at=last.first_seen_at))
            written += 1
    if written:
        await db.commit()
    return written


async def history_start(db: AsyncSession, project_id: uuid.UUID) -> datetime | None:
    return (await db.execute(select(func.min(UrlStatusHistory.valid_from)).where(UrlStatusHistory.project_id == project_id))).scalar_one()


async def status_as_of(db: AsyncSession, project_id: uuid.UUID, thin_words: int, as_of: datetime) -> tuple[list[dict[str, Any]], str]:
    """The per-URL status at `as_of` and its basis: "stored" when the exact history covers the date (what Helm
    showed then), otherwise "reconstructed" from the inspection and signal history with today's rules."""
    start = await history_start(db, project_id)
    if start is not None and start <= as_of:
        latest = await _latest_history(db, project_id, as_of)
        rows = [
            {
                "id": None, "url": url, "lastmod": None, "first_seen_at": h.first_seen_at,
                **{f: getattr(h, f) for f in STATUS_FIELDS},
            }
            for url, h in sorted(latest.items())
            if h.issue is not None
        ]
        return rows, "stored"
    return await url_statuses(db, project_id, thin_words, as_of), "reconstructed"


def count_issues(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(r["issue"] for r in rows)
    return {issue: counts.get(issue, 0) for issue in rules.ISSUES}


async def record_snapshot(
    db: AsyncSession, project_id: uuid.UUID, thin_words: int, today: date | None = None, now: datetime | None = None
) -> dict:
    await record_status_history(db, project_id, thin_words, now)
    rows = await url_statuses(db, project_id, thin_words)
    counts = count_issues(rows)
    today = today or datetime.now(timezone.utc).date()
    statement = insert(IndexingSnapshot).values(
        project_id=project_id, snapshot_date=today, total_urls=len(rows), counts=counts
    )
    statement = statement.on_conflict_do_update(
        index_elements=["project_id", "snapshot_date"],
        set_={"total_urls": statement.excluded.total_urls, "counts": statement.excluded.counts},
    )
    await db.execute(statement)
    await db.commit()
    return counts


def indexed_percent(counts: dict[str, int]) -> float | None:
    total = sum(counts.values()) - counts.get(rules.UNKNOWN, 0)
    return round(100 * counts.get(rules.INDEXED, 0) / total, 1) if total else None
