"""Keyword generator: seeds (our data) -> Claude expansion -> volume -> gap + scoring -> proposed candidates.

Nothing here publishes anything. Candidates start as `proposed`; the owner accepts or rejects them.
"""
import hashlib
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_setting
from app.indexing import service as indexing_service
from app.keywords import llm as llm_mod
from app.keywords import planner as planner_mod
from app.keywords import queries, scoring
from app.models.indexing import KeywordCandidate, KeywordRun
from app.models.project import Project

logger = logging.getLogger("helm.keywords")

PROMPT_VERSION = "v1"
MAX_LLM_CANDIDATES = 60
MAX_SEED_QUERIES = 100
MAX_SEED_TITLES = 120
MAX_AVOID_KEYWORDS = 150
MIN_STRIKING_IMPRESSIONS_FOR_CANDIDATE = scoring.STRIKING_MIN_IMPRESSIONS
STALE_RUN_MINUTES = 30
INTENTS = ["informational", "commercial", "navigational", "transactional"]

SYSTEM_PROMPT = """You are an SEO strategist proposing target keywords for one website.
Work only from the site context given. Group keywords into clusters: one cluster is one article or page that
should rank for all of its keywords. Prefer specific, searchable phrases a real person would type, in the
site's own language and market. Do not repeat any keyword or page topic listed as already covered. Do not
invent statistics or search volumes. relevance is 0 to 1: how well the keyword fits the site's topic and audience."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "intent": {"type": "string", "enum": INTENTS},
                    "keywords": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"keyword": {"type": "string"}, "relevance": {"type": "number"}},
                            "required": ["keyword", "relevance"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["label", "intent", "keywords"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


class GeneratorError(RuntimeError):
    pass


@dataclass
class Draft:
    keyword: str
    source: str  # gsc | llm
    intent: str | None = None
    cluster_id: str | None = None
    cluster_label: str | None = None
    relevance: float | None = None
    target_url: str | None = None


@dataclass
class PageInfo:
    url: str
    title: str
    tokens: frozenset = field(default_factory=frozenset)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "cluster"


def page_cluster_id(url: str) -> str:
    return "page-" + hashlib.sha1(url.encode()).hexdigest()[:10]


def _tokens(text: str) -> frozenset:
    return frozenset(scoring.normalise_keyword(text).split())


def match_page(keyword: str, pages: list[PageInfo]) -> str | None:
    """An existing page whose title contains every word of the keyword, preferring the shortest title (closest topic)."""
    words = _tokens(keyword)
    if not words:
        return None
    fits = [p for p in pages if words <= p.tokens]
    return min(fits, key=lambda p: len(p.tokens)).url if fits else None


def build_prompt(project: Project, top_queries: list[queries.QueryStat], titles: list[str], avoid: list[str]) -> str:
    lines = [
        f"Site: {project.name} ({project.url})",
        f"Category: {project.category}",
        f"Goals: {project.goals or 'not stated'}",
        "",
        "Queries the site already gets impressions for (query | impressions | avg position):",
    ]
    lines += [f"- {s.query} | {s.impressions} | {s.position}" for s in top_queries] or ["- (no Search Console data yet)"]
    lines += ["", "Existing page titles (topics already covered):"]
    lines += [f"- {t}" for t in titles] or ["- (none known yet)"]
    lines += ["", "Keywords already proposed or decided (do not repeat):"]
    lines += [f"- {k}" for k in avoid] or ["- (none)"]
    lines += ["", f"Propose up to {MAX_LLM_CANDIDATES} new keywords in clusters, mixing intents."]
    return "\n".join(lines)


def parse_llm_drafts(payload: dict) -> list[Draft]:
    drafts, seen = [], set()
    for cluster in payload.get("clusters", []):
        label = (cluster.get("label") or "").strip() or "Unnamed cluster"
        intent = cluster.get("intent") if cluster.get("intent") in INTENTS else None
        cluster_id = "llm-" + slugify(label)
        for entry in cluster.get("keywords", []):
            keyword = scoring.normalise_keyword(str(entry.get("keyword", "")))
            if not keyword or len(keyword) > 200 or keyword in seen:
                continue
            seen.add(keyword)
            relevance = entry.get("relevance")
            drafts.append(
                Draft(
                    keyword=keyword,
                    source="llm",
                    intent=intent,
                    cluster_id=cluster_id,
                    cluster_label=label,
                    relevance=float(relevance) if isinstance(relevance, (int, float)) else None,
                )
            )
            if len(drafts) >= MAX_LLM_CANDIDATES:
                return drafts
    return drafts


def striking_drafts(stats: list[queries.QueryStat]) -> list[Draft]:
    """Queries already at positions 8-20: the free, highest-value candidates (improve the page that ranks)."""
    drafts = []
    for s in queries.striking_distance(stats):
        keyword = scoring.normalise_keyword(s.query)
        if keyword:
            drafts.append(
                Draft(
                    keyword=keyword,
                    source="gsc",
                    cluster_id=page_cluster_id(s.top_page or keyword),
                    cluster_label=s.top_page,
                    target_url=s.top_page,
                    relevance=1.0,
                )
            )
    return drafts


async def _pages(db: AsyncSession, project_id: uuid.UUID) -> list[PageInfo]:
    signals = await indexing_service.latest_signals(db, project_id)
    return [
        PageInfo(url=url, title=sig.title, tokens=_tokens(sig.title))
        for url, sig in signals.items()
        if sig.title and sig.http_status == 200 and not sig.noindex
    ]


def _planner_values(found: dict, keyword: str):
    metric = found.get(keyword)
    if metric is None:
        return None, False, None
    return metric.avg_monthly_searches, bool(metric.is_bucket), metric.competition_index


def finalise(
    draft: Draft,
    stat: queries.QueryStat | None,
    pages: list[PageInfo],
    found: dict,
    weights: dict,
) -> dict:
    """Everything stored on a candidate except identity and status."""
    volume, is_bucket, competition = _planner_values(found, draft.keyword)
    gsc_estimate = stat.estimated_monthly_searches if stat else None
    demand_est, demand_source = scoring.resolve_demand(gsc_estimate, volume, is_bucket)
    target = draft.target_url or (stat.top_page if stat else None) or match_page(draft.keyword, pages)
    gap = scoring.classify_gap(stat.position if stat else None, stat.impressions if stat else None, has_page=target is not None)
    cluster_id = draft.cluster_id or (page_cluster_id(target) if target else "kw-" + slugify(draft.keyword))
    return {
        "cluster_id": cluster_id,
        "cluster_label": draft.cluster_label or target or draft.keyword,
        "intent": draft.intent,
        "volume": volume,
        "volume_is_bucket": is_bucket,
        "competition": competition,
        "impressions_proxy": stat.impressions if stat else None,
        "position_avg": stat.position if stat else None,
        "demand_est": demand_est,
        "demand_source": demand_source,
        "gap": gap,
        "score": scoring.score_candidate(demand_est, gap, draft.relevance, competition, demand_source, weights),
        "target_url": target,
    }


async def start_run(db: AsyncSession, project_id: uuid.UUID, now: datetime | None = None) -> KeywordRun:
    """Creates the run row; refuses a second run while a recent one is still going."""
    now = now or datetime.now(timezone.utc)
    running = (
        await db.execute(
            select(func.count()).select_from(KeywordRun).where(
                KeywordRun.project_id == project_id,
                KeywordRun.status == "running",
                KeywordRun.started_at > now - timedelta(minutes=STALE_RUN_MINUTES),
            )
        )
    ).scalar_one()
    if running:
        raise GeneratorError("a keyword run is already in progress for this project")
    run = KeywordRun(project_id=project_id, prompt_version=PROMPT_VERSION, status="running", started_at=now)
    db.add(run)
    await db.commit()
    return run




async def execute_run(
    session_factory: Callable,
    run_id: uuid.UUID,
    llm: llm_mod.LlmCall | None = None,
    planner: planner_mod.PlannerClient | None = None,
    use_llm: bool = True,
) -> KeywordRun:
    """Runs the pipeline for an existing `running` row and always leaves it `ok` or `error`."""
    llm = llm or llm_mod.call_claude
    planner = planner or planner_mod.PlannerClient()
    async with session_factory() as db:
        run = await db.get(KeywordRun, run_id)
        try:
            await _pipeline(db, run, llm, planner, use_llm)
            run.status = "ok"
        except Exception as exc:  # noqa: BLE001 -- recorded on the run for the UI, never raised into the background task
            await db.rollback()
            run = await db.get(KeywordRun, run_id)
            run.status = "error"
            run.error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning("keyword run %s failed: %s", run_id, run.error)
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return run


async def _pipeline(db: AsyncSession, run: KeywordRun, llm, planner, use_llm: bool) -> None:
    project = await db.get(Project, run.project_id)
    weights = await get_setting(db, "scoring_weights")
    volume_source = await get_setting(db, "volume_source")
    cap = await get_setting(db, "llm_daily_cap_usd")

    stats = await queries.query_stats(db, project.id)
    stat_lookup = queries.by_normalised_query(stats)
    pages = await _pages(db, project.id)
    existing = {
        c.keyword: c for c in (await db.execute(select(KeywordCandidate).where(KeywordCandidate.project_id == project.id))).scalars()
    }

    drafts = {d.keyword: d for d in striking_drafts(stats)}
    counts = {"gsc_striking": len(drafts), "llm": 0, "queries_seen": len(stats), "pages_known": len(pages)}

    if use_llm:
        await llm_mod.check_cap(db, cap)
        avoid = list(existing)[:MAX_AVOID_KEYWORDS]
        prompt = build_prompt(project, stats[:MAX_SEED_QUERIES], [p.title for p in pages][:MAX_SEED_TITLES], avoid)
        reply = await llm(SYSTEM_PROMPT, prompt, SCHEMA)
        run.model, run.raw_output = reply.model, reply.text
        run.cost_usd = await llm_mod.record_spend(db, project.id, reply)
        covered = {scoring.normalise_keyword(p.title) for p in pages}
        for draft in parse_llm_drafts(reply.json()):
            if draft.keyword in drafts or draft.keyword in covered:
                continue
            drafts[draft.keyword] = draft
            counts["llm"] += 1

    found: dict = {}
    if volume_source == "keyword_planner":
        if planner.configured:
            found = await planner_mod.lookup(db, planner, list(drafts))
            counts["planner_metrics"] = len(found)
        else:
            counts["planner_skipped"] = "not configured"
    run.source_counts = counts

    now = datetime.now(timezone.utc)
    for keyword, draft in drafts.items():
        values = finalise(draft, stat_lookup.get(keyword), pages, found, weights)
        row = existing.get(keyword)
        if row is None:
            db.add(KeywordCandidate(project_id=project.id, run_id=run.id, keyword=keyword, source=draft.source, **values))
        else:
            # Refresh numbers on every run; never touch a decision the owner already made.
            for attr, value in values.items():
                setattr(row, attr, value)
            if row.status == "proposed":
                row.run_id = run.id
    # Candidates that have since gained impressions get their stats refreshed too, even if no longer drafted.
    for keyword, row in existing.items():
        if keyword in drafts or keyword not in stat_lookup:
            continue
        stat = stat_lookup[keyword]
        row.impressions_proxy, row.position_avg = stat.impressions, stat.position
    await db.commit()
    run.finished_at = now
