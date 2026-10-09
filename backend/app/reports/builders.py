"""Report builders. Every report answers for a date (`as_of`, UTC, inclusive). With no date, or today's date,
the four original reports behave exactly as before (the current state)."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_setting
from app.indexing import classify as rules
from app.indexing import rankings, service
from app.keywords import queries
from app.keywords.rollup import week_start as monday_of
from app.models.indexing import KeywordCandidate, WeeklyDigest
from app.models.project import Project, TrafficDaily, TrafficSnapshot
from app.reports import availability
from app.reports.catalog import BY_NAME, GRANULARITIES

HEALTHY = {rules.INDEXED, rules.UNKNOWN}
DEFAULT_DIGEST_WEEKS = 26
MAX_DIGEST_WEEKS = 520
DEFAULT_TRAFFIC_DAYS = 28
MAX_TRAFFIC_DAYS = 3660


@dataclass
class Params:
    as_of: date
    today: date
    granularity: str = "total"
    days: int = DEFAULT_TRAFFIC_DAYS
    weeks: int = DEFAULT_DIGEST_WEEKS
    latest_week_only: bool = False  # digest, when comparing: just the newest week up to the date

    @property
    def is_current(self) -> bool:
        return self.as_of >= self.today


@dataclass
class Report:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "columns": self.columns, "rows": self.rows, "meta": self.meta}


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


async def _status_rows(db: AsyncSession, project: Project, thin: int, p: Params) -> tuple[list[dict], str]:
    if p.is_current:
        return await service.url_statuses(db, project.id, thin), "current"
    return await service.status_as_of(db, project.id, thin, service.end_of_day(p.as_of))


def _worst(bases: list[str]) -> str:
    for basis in ("reconstructed", "stored", "current"):
        if basis in bases:
            return basis
    return "current"


async def _indexing(db, projects, thin, p):
    columns = ["project", "total_urls", *rules.ISSUES, "indexed_percent"]
    rows, bases = [], []
    for project in projects:
        statuses, basis = await _status_rows(db, project, thin, p)
        bases.append(basis)
        counts = service.count_issues(statuses)
        rows.append([project.name, sum(counts.values()), *[counts[i] for i in rules.ISSUES], service.indexed_percent(counts)])
    return columns, rows, _worst(bases)


async def _non_indexed(db, projects, thin, p):
    columns = ["project", "url", "issue", "coverage_state", "last_crawl_time", "word_count", "http_status", "title"]
    rows, bases = [], []
    for project in projects:
        statuses, basis = await _status_rows(db, project, thin, p)
        bases.append(basis)
        for r in statuses:
            if r["issue"] not in HEALTHY:
                rows.append([project.name, r["url"], r["issue"], r["coverage_state"], r["last_crawl_time"], r["word_count"], r["http_status"], r["title"]])
    rows.sort(key=lambda r: (r[0], r[2], r[1]))
    return columns, rows, _worst(bases)


async def _urls(db, projects, thin, p):
    columns = ["project", "url", "issue", "coverage_state", "last_crawl_time", "word_count", "http_status", "title", "first_seen_at"]
    rows, bases = [], []
    for project in projects:
        statuses, basis = await _status_rows(db, project, thin, p)
        bases.append(basis)
        for r in statuses:
            rows.append([project.name, r["url"], r["issue"], r["coverage_state"], r["last_crawl_time"], r["word_count"], r["http_status"], r["title"], r["first_seen_at"]])
    rows.sort(key=lambda r: (r[0], r[1]))
    return columns, rows, _worst(bases)


async def _striking(db, projects, thin, p):
    columns = ["project", "query", "page", "position", "impressions", "clicks"]
    rows = []
    for project in projects:
        stats = await queries.query_stats(db, project.id, today=p.as_of)
        for s in queries.striking_distance(stats):
            rows.append([project.name, s.query, s.top_page, s.position, s.impressions, s.clicks])
    return columns, rows, "stored"


async def _cannibalisation(db, projects, thin, p):
    columns = ["project", "query", "pages", "impressions", "clicks", "position", "top_page"]
    rows = []
    for project in projects:
        for s in queries.cannibalised(await queries.query_stats(db, project.id, today=p.as_of)):
            rows.append([project.name, s.query, s.pages, s.impressions, s.clicks, s.position, s.top_page])
    return columns, rows, "stored"


async def _rankings(db, projects, thin, p):
    columns = ["project", "url", "position", "position_prior", "position_change", "clicks", "impressions", "top_query", "indexing"]
    rows = []
    for project in projects:
        data = await rankings.page_rankings(db, project, weeks=4, min_impressions=10, limit=rankings.MAX_PAGES, as_of=None if p.is_current else p.as_of)
        for page in data["pages"]:
            top = page["top_queries"][0]["query"] if page["top_queries"] else None
            rows.append([project.name, page["url"], page["position"], page["position_prior"], page["position_change"], page["clicks"], page["impressions"], top, page["indexing"]])
    return columns, rows, "stored"


async def _digest(db, projects, thin, p):
    columns = ["project", "week_start", "clicks", "clicks_change_pct", "impressions", "impressions_change_pct", "indexed_percent", "striking_distance", "pending_keywords"]
    rows = []
    for project in projects:
        stmt = select(WeeklyDigest).where(WeeklyDigest.project_id == project.id)
        if not p.is_current:
            stmt = stmt.where(WeeklyDigest.week_start <= p.as_of - timedelta(days=6))  # the week had ended by then
        limit = 1 if p.latest_week_only else max(1, min(p.weeks, MAX_DIGEST_WEEKS))
        for d in (await db.execute(stmt.order_by(WeeklyDigest.week_start.desc()).limit(limit))).scalars():
            t = d.payload.get("traffic", {})
            rows.append([
                project.name, d.week_start, t.get("clicks"), t.get("clicks_change_pct"), t.get("impressions"), t.get("impressions_change_pct"),
                d.payload.get("indexing", {}).get("indexed_percent"), d.payload.get("striking_distance"), d.payload.get("pending_keyword_candidates"),
            ])
    rows.sort(key=lambda r: (r[1], r[0]), reverse=True)
    return columns, rows, "stored"


def _bucket(day: date, granularity: str, start: date, end: date) -> tuple[date, date]:
    if granularity == "day":
        return day, day
    if granularity == "week":
        monday = monday_of(day)
        return max(monday, start), min(monday + timedelta(days=6), end)
    if granularity == "month":
        first = day.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return max(first, start), min(nxt - timedelta(days=1), end)
    return start, end


async def _traffic(db, projects, thin, p):
    columns = ["project", "period_start", "period_end", "clicks", "impressions", "ctr", "position", "sessions"]
    end = p.as_of
    start = end - timedelta(days=max(1, min(p.days, MAX_TRAFFIC_DAYS)) - 1)
    rows = []
    for project in projects:
        data = (
            await db.execute(select(TrafficDaily).where(TrafficDaily.project_id == project.id, TrafficDaily.metric_date >= start, TrafficDaily.metric_date <= end))
        ).scalars().all()
        buckets: dict[tuple[date, date], list] = defaultdict(list)
        for r in data:
            buckets[_bucket(r.metric_date, p.granularity, start, end)].append(r)
        for (b_start, b_end), items in sorted(buckets.items()):
            clicks = sum(r.clicks or 0 for r in items)
            impressions = sum(r.impressions or 0 for r in items)
            weighted = sum((r.avg_position or 0) * (r.impressions or 0) for r in items if r.avg_position is not None)
            has_sessions = any(r.sessions is not None for r in items)
            rows.append([
                project.name, b_start, b_end, clicks, impressions,
                round(clicks / impressions, 4) if impressions else None,
                round(weighted / impressions, 2) if impressions and weighted else None,
                sum(r.sessions or 0 for r in items) if has_sessions else None,
            ])
    rows.sort(key=lambda r: (r[0], r[1]))
    return columns, rows, "stored"


async def _alerts(db, projects, thin, p):
    """The alerts a collector run had saved by the end of the date: the newest snapshot per project on or before it."""
    columns = ["project", "kind", "severity", "message", "recorded_at"]
    end = service.end_of_day(p.as_of)
    rows = []
    for project in projects:
        snap = (
            await db.execute(
                select(TrafficSnapshot).where(TrafficSnapshot.project_id == project.id, TrafficSnapshot.synced_at <= end).order_by(TrafficSnapshot.synced_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        for alert in (snap.alert_messages or []) if snap else []:
            rows.append([project.name, alert.get("kind"), alert.get("severity"), alert.get("message"), snap.synced_at])
    rows.sort(key=lambda r: (r[0], 0 if r[2] == "red" else 1, r[3] or ""))
    return columns, rows, "stored"


async def _keywords(db, projects, thin, p):
    columns = ["project", "keyword", "status", "score", "intent", "cluster", "volume", "demand_source", "target_url", "created_at", "decided_at"]
    end = service.end_of_day(p.as_of)
    rows = []
    for project in projects:
        candidates = (
            await db.execute(select(KeywordCandidate).where(KeywordCandidate.project_id == project.id, KeywordCandidate.created_at <= end).order_by(KeywordCandidate.score.desc()))
        ).scalars().all()
        for c in candidates:
            decided = c.decided_at is not None and c.decided_at <= end
            status = c.status if (c.status == "proposed" or decided) else "proposed"
            rows.append([project.name, c.keyword, status, c.score, c.intent, c.cluster_label or c.cluster_id, c.volume, c.demand_source, c.target_url, c.created_at, c.decided_at if decided else None])
    return columns, rows, "stored"


BUILDERS = {
    "indexing": _indexing,
    "non-indexed": _non_indexed,
    "urls": _urls,
    "striking-distance": _striking,
    "cannibalisation": _cannibalisation,
    "rankings": _rankings,
    "digest": _digest,
    "traffic": _traffic,
    "alerts": _alerts,
    "keywords": _keywords,
}


async def build(db: AsyncSession, projects: list[Project], name: str, p: Params) -> Report:
    if name not in BUILDERS:
        raise KeyError(name)
    if p.granularity not in GRANULARITIES:
        raise ValueError(f"granularity must be one of: {', '.join(GRANULARITIES)}")
    first, last = await availability.bounds(db, name, [x.id for x in projects], p.today)
    meta: dict[str, Any] = {
        "as_of": p.as_of, "available_from": first, "available_to": last, "history": BY_NAME[name].history, "note": None,
    }
    note = availability.out_of_range_note(name, p.as_of, first, last)
    spec_columns = (await BUILDERS[name](db, [], 0, p))[0]
    if note and not (name == "traffic" and last is not None and p.as_of > last):
        meta.update(basis="none", note=note, out_of_range=True)
        return Report(name, spec_columns, [], meta)
    thin = await get_setting(db, "thin_word_threshold")
    columns, rows, basis = await BUILDERS[name](db, projects, thin, p)
    meta.update(basis=basis, out_of_range=False)
    if note:
        meta["note"] = note
    elif basis == "reconstructed":
        meta["note"] = "Reconstructed from inspection history with today's classification rules; exact stored status starts later."
    elif name == "keywords" and not p.is_current:
        meta["note"] = "Status is as of the date; a 'written' status is shown from the day the keyword was decided."
    return Report(name, columns, rows, meta)
