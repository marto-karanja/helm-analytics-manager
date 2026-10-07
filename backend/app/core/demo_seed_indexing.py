"""Frozen demo data for indexing, sitemaps, keywords and the weekly digest.

Deterministic (plain formulas, no randomness) and clearly synthetic: the URLs are sample paths on the demo
projects' hosts, and every number is a fixed label, never a live figure.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing import classify as rules
from app.indexing import service as indexing_service
from app.models.indexing import (
    GscQueryRollup,
    IndexingSnapshot,
    KeywordCandidate,
    PageSignal,
    SitemapStatus,
    SitemapUrl,
    UrlInspection,
    WeeklyDigest,
)
from app.models.project import Project

URLS_PER_PROJECT = 24
TOPICS = [
    "getting-started", "pricing-guide", "common-mistakes", "buyers-checklist", "comparison", "faq", "case-study",
    "how-it-works", "regulations", "tools-and-templates", "beginner-tips", "advanced-tips", "seasonal-guide",
    "troubleshooting", "glossary", "local-options", "cost-breakdown", "step-by-step", "myths", "reviews",
    "alternatives", "tutorial", "roundup", "resources",
]
# index -> (coverage_state, verdict, word_count, noindex) for the non-indexed minority; everything else is indexed.
PROBLEMS = {
    3: ("Crawled - currently not indexed", "NEUTRAL", 900, False),
    9: ("Crawled - currently not indexed", "NEUTRAL", 820, False),
    14: ("Crawled - currently not indexed", "NEUTRAL", 1100, False),
    5: ("Discovered - currently not indexed", "NEUTRAL", 760, False),
    18: ("Discovered - currently not indexed", "NEUTRAL", 640, False),
    7: ("Submitted and indexed", "PASS", 180, False),  # thin
    21: ("Submitted and indexed", "PASS", 240, False),  # thin
    11: ("Excluded by 'noindex' tag", "NEUTRAL", 700, True),
}
CANDIDATES = [
    ("how to choose a {t}", "informational", "no_page", 62.4, "proposed", None),
    ("best {t} for beginners", "commercial", "no_page", 58.1, "proposed", None),
    ("{t} cost per month", "commercial", "striking_distance", 71.9, "proposed", "/guides/pricing-guide"),
    ("{t} checklist", "informational", "other", 49.3, "accepted", "/guides/buyers-checklist"),
    ("{t} common mistakes", "informational", "no_page", 44.0, "accepted", None),
    ("free {t} templates", "transactional", "no_page", 31.2, "rejected", None),
    ("{t} near me", "navigational", "no_page", 27.8, "rejected", None),
    ("{t} rules and regulations", "informational", "striking_distance", 66.0, "proposed", "/guides/regulations"),
]
QUERIES = [
    ("cost per month", "/guides/pricing-guide", 14.2, 420),
    ("rules and regulations", "/guides/regulations", 11.8, 260),
    ("beginner tips", "/guides/beginner-tips", 9.4, 180),
    ("checklist", "/guides/buyers-checklist", 3.1, 900),
    ("comparison", "/guides/comparison", 6.5, 640),
]


def _utc(day: date, hour: int = 8) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour)


async def seed_project_indexing(session: AsyncSession, project: Project, index: int, snapshot_day: date) -> None:
    base = project.url.rstrip("/")
    topic = project.name.lower().replace(" ", "")
    frozen = _utc(snapshot_day)
    urls = []
    for i in range(URLS_PER_PROJECT):
        path = f"/guides/{TOPICS[i]}"
        url = f"{base}{path}"
        urls.append(url)
        coverage, verdict, words, noindex = PROBLEMS.get(i, ("Submitted and indexed", "PASS", 1200 + (i * 37 + index * 11) % 600, False))
        session.add(
            SitemapUrl(
                project_id=project.id, url=url, source_sitemap=f"{base}/sitemap.xml",
                lastmod=_utc(snapshot_day - timedelta(days=i * 3)), first_seen_at=_utc(snapshot_day - timedelta(days=90)), last_seen_at=frozen,
            )
        )
        session.add(
            PageSignal(
                project_id=project.id, url=url, fetched_at=frozen, http_status=200, title=f"Sample guide {i + 1}: {TOPICS[i].replace('-', ' ')}",
                meta_description="Demo data.", word_count=words, h1_count=1, h2_count=4 + i % 3, internal_links=6 + i % 5, noindex=noindex,
                content_hash=f"demo-{project.slug}-{i}", source="http", headings=[],
            )
        )
        session.add(
            UrlInspection(
                project_id=project.id, url=url, inspected_at=frozen, verdict=verdict, coverage_state=coverage,
                indexing_state="BLOCKED_BY_META_TAG" if noindex else "INDEXING_ALLOWED", robots_txt_state="ALLOWED",
                page_fetch_state="SUCCESSFUL", last_crawl_time=_utc(snapshot_day - timedelta(days=2 + i % 6)), crawled_as="MOBILE",
            )
        )
    await session.flush()

    # A rising indexed count over the last 12 weeks, ending at today's real classification.
    thin = rules.DEFAULT_THIN_WORDS
    final = indexing_service.count_issues(await indexing_service.url_statuses(session, project.id, thin))
    for step in range(12):
        day = snapshot_day - timedelta(days=7 * (11 - step))
        indexed = max(0, final[rules.INDEXED] - (11 - step) // 2)
        counts = {**final, rules.INDEXED: indexed, rules.UNKNOWN: final[rules.UNKNOWN] + (final[rules.INDEXED] - indexed)}
        session.add(IndexingSnapshot(project_id=project.id, snapshot_date=day, total_urls=URLS_PER_PROJECT, counts=counts))

    session.add(
        SitemapStatus(
            project_id=project.id, path=f"{base}/sitemap.xml", last_submitted=_utc(snapshot_day - timedelta(days=30)),
            last_downloaded=frozen, is_pending=False, errors=0, warnings=index % 2, submitted_urls=URLS_PER_PROJECT, indexed_urls=final[rules.INDEXED],
        )
    )

    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    for query, page, position, impressions in QUERIES:
        for week in range(1, 5):  # the four complete weeks the generator looks at
            session.add(
                GscQueryRollup(
                    project_id=project.id, week_start=this_monday - timedelta(weeks=week), query=f"{topic} {query}", page=f"{base}{page}",
                    impressions=impressions // 4 + index, position_avg=position, clicks=max(1, impressions // 60),
                )
            )

    for k, (template, intent, gap, score, status, target) in enumerate(CANDIDATES):
        session.add(
            KeywordCandidate(
                project_id=project.id, keyword=template.format(t=topic), intent=intent, gap=gap, score=score + index, status=status, source="llm" if k % 3 else "gsc",
                target_url=f"{base}{target}" if target else None, cluster_label=f"Cluster {k // 2 + 1}", cluster_id=f"demo-{k // 2}",
                demand_est=float(300 * (k + 1)), demand_source="gsc" if gap == "striking_distance" else "none",
                impressions_proxy=int(120 * (k + 1)) if gap == "striking_distance" else None,
                position_avg=12.5 if gap == "striking_distance" else None,
                decided_at=frozen if status in {"accepted", "rejected"} else None,
            )
        )

    last_monday = this_monday - timedelta(days=7)
    for week in range(6):
        monday = last_monday - timedelta(weeks=week)
        clicks = 400 + index * 30 + (5 - week) * 25
        previous = clicks - 20
        session.add(
            WeeklyDigest(
                project_id=project.id, week_start=monday, created_at=_utc(monday + timedelta(days=7)),
                payload={
                    "week_start": monday.isoformat(),
                    "traffic": {
                        "clicks": clicks, "impressions": clicks * 18, "sessions": clicks * 85 // 100,
                        "previous": {"clicks": previous, "impressions": previous * 18, "sessions": previous * 85 // 100},
                        "clicks_change_pct": round(100 * (clicks - previous) / previous, 1),
                        "impressions_change_pct": round(100 * (clicks - previous) / previous, 1),
                    },
                    "indexing": {"counts": final, "indexed_percent": indexing_service.indexed_percent(final)},
                    "top_queries": [{"query": f"{topic} {q}", "clicks": c // 60, "impressions": c // 4} for q, _, _, c in QUERIES[:3]],
                    "striking_distance": 3, "pending_keyword_candidates": 4,
                },
            )
        )
