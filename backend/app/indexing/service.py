"""Read side of indexing analysis: latest inspection + latest signals per sitemap URL, classified on demand.

Computed in Python, not a SQL view, because the thin-content threshold is an editable setting and
duplicate detection compares rows against each other.
"""
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing import classify as rules
from app.models.indexing import IndexingSnapshot, PageSignal, SitemapUrl, UrlInspection


async def live_urls(db: AsyncSession, project_id: uuid.UUID) -> list[SitemapUrl]:
    result = await db.execute(
        select(SitemapUrl).where(SitemapUrl.project_id == project_id, SitemapUrl.removed_at.is_(None)).order_by(SitemapUrl.url)
    )
    return list(result.scalars().all())


async def latest_inspections(db: AsyncSession, project_id: uuid.UUID) -> dict[str, UrlInspection]:
    result = await db.execute(
        select(UrlInspection)
        .where(UrlInspection.project_id == project_id)
        .distinct(UrlInspection.url)
        .order_by(UrlInspection.url, UrlInspection.inspected_at.desc())
    )
    return {row.url: row for row in result.scalars()}


async def latest_signals(db: AsyncSession, project_id: uuid.UUID) -> dict[str, PageSignal]:
    result = await db.execute(
        select(PageSignal)
        .where(PageSignal.project_id == project_id)
        .distinct(PageSignal.url)
        .order_by(PageSignal.url, PageSignal.fetched_at.desc())
    )
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


async def url_statuses(db: AsyncSession, project_id: uuid.UUID, thin_words: int) -> list[dict[str, Any]]:
    """One row per live sitemap URL with its primary issue, newest signals and newest inspection."""
    urls = await live_urls(db, project_id)
    inspections = await latest_inspections(db, project_id)
    signals = await latest_signals(db, project_id)
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


def count_issues(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(r["issue"] for r in rows)
    return {issue: counts.get(issue, 0) for issue in rules.ISSUES}


async def record_snapshot(db: AsyncSession, project_id: uuid.UUID, thin_words: int, today: date | None = None) -> dict:
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
