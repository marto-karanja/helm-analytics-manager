"""Demand estimation and scoring. Pure functions, no I/O, so every rule is unit-tested."""
import math
import re

# Share of searchers who ever see a given result position. Position 1-10 is page one; deeper pages are
# reached by few people, so impressions there understate how often the query is searched.
VISIBILITY_BY_POSITION = ((10.5, 1.0), (20.5, 0.25), (30.5, 0.08))
VISIBILITY_DEEPER = 0.03

STRIKING_MIN_POSITION = 8.0
STRIKING_MAX_POSITION = 20.0
STRIKING_MIN_IMPRESSIONS = 10
RANKING_WELL_POSITION = 5.0

# demand_source values, ordered best to worst
GSC, KP_EXACT, KP_BUCKET, NONE = "gsc", "kp_exact", "kp_bucket", "none"
CONFIDENCE = {GSC: 1.0, KP_EXACT: 0.95, KP_BUCKET: 0.7, NONE: 0.5}

# Keyword Planner reports coarse ranges for accounts without ad spend; those come back as round numbers.
BUCKET_VALUES = {10, 100, 1000, 10_000, 100_000, 1_000_000}

DEMAND_LOG_CEILING = 100_000  # monthly searches that map to a demand score of 1.0

GAP_SCORES = {"striking_distance": 1.0, "no_page": 0.7, "other": 0.3, "ranking": 0.1}

_NORMALISE = re.compile(r"[^\w\s'-]", re.UNICODE)


def normalise_keyword(keyword: str) -> str:
    return " ".join(_NORMALISE.sub(" ", keyword.lower()).split())


def visibility(position: float) -> float:
    for limit, share in VISIBILITY_BY_POSITION:
        if position < limit:
            return share
    return VISIBILITY_DEEPER


def estimate_monthly_searches(impressions_4w: int, position: float) -> float:
    """Searches per month implied by four weeks of Search Console impressions at an average position."""
    if impressions_4w <= 0:
        return 0.0
    return impressions_4w / visibility(position)


def is_striking_distance(position: float | None, impressions: int | None) -> bool:
    return (
        position is not None
        and impressions is not None
        and STRIKING_MIN_POSITION <= position <= STRIKING_MAX_POSITION
        and impressions >= STRIKING_MIN_IMPRESSIONS
    )


def looks_like_bucket(avg_monthly_searches: int | None, monthly: list[int] | None = None) -> bool:
    """Heuristic: a round power of ten, or twelve identical months, is a range midpoint, not a measurement."""
    if avg_monthly_searches is None:
        return False
    if avg_monthly_searches in BUCKET_VALUES:
        return True
    return bool(monthly) and len(monthly) >= 6 and len(set(monthly)) == 1 and monthly[0] in BUCKET_VALUES


def classify_gap(position: float | None, impressions: int | None, has_page: bool) -> str:
    if not has_page:
        return "no_page"
    if is_striking_distance(position, impressions):
        return "striking_distance"
    if position is not None and position <= RANKING_WELL_POSITION:
        return "ranking"
    return "other"


def resolve_demand(gsc_estimate: float | None, volume: int | None, is_bucket: bool) -> tuple[float | None, str]:
    """Best available demand figure and where it came from.

    An exact Keyword Planner volume covers searches we never appeared for, so it wins; Search Console's
    own impressions come next (measured, but only for queries we already surface for); a bucketed volume
    is only a range midpoint and ranks last among real numbers.
    """
    if volume is not None and not is_bucket:
        return float(max(volume, gsc_estimate or 0)), KP_EXACT
    if gsc_estimate:
        return gsc_estimate, GSC
    if volume is not None:
        return float(volume), KP_BUCKET
    return None, NONE


def demand_score(demand_est: float | None) -> float:
    if not demand_est or demand_est <= 0:
        return 0.0
    return min(1.0, math.log10(1 + demand_est) / math.log10(1 + DEMAND_LOG_CEILING))


def score_candidate(
    demand_est: float | None,
    gap: str,
    relevance: float | None,
    competition: float | None,
    demand_source: str,
    weights: dict[str, float],
) -> float:
    """0-100. Competition is advertiser competition (Keyword Planner index, 0-1), a weak proxy, so it is
    weighted low and treated as neutral when unknown. Low-confidence demand data scales the score down so a
    shaky number cannot rank a candidate first."""
    components = {
        "demand": demand_score(demand_est),
        "gap": GAP_SCORES.get(gap, GAP_SCORES["other"]),
        "relevance": 0.5 if relevance is None else max(0.0, min(1.0, relevance)),
        "competition": 0.5 if competition is None else 1.0 - max(0.0, min(1.0, competition)),
    }
    total_weight = sum(weights.values()) or 1.0
    weighted = sum(weights[key] * components[key] for key in components) / total_weight
    return round(100 * weighted * CONFIDENCE[demand_source], 1)
