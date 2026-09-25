from datetime import date, timedelta

# Search Console data is provisional for a couple of days, so the comparison windows end 3 days back.
GSC_LAG_DAYS = 3
WINDOW_DAYS = 7


def _trend(recent: int, prior: int) -> dict:
    pct_change = round((recent - prior) / prior * 100, 1) if prior > 0 else None
    return {"recent": recent, "prior": prior, "pct_change": pct_change}


def _sum_trend(recent_rows: list[dict], prior_rows: list[dict], column: str) -> dict | None:
    """None when the column has no data at all (that source is not collected for the project)."""
    recent_values = [r[column] for r in recent_rows if r.get(column) is not None]
    prior_values = [r[column] for r in prior_rows if r.get(column) is not None]
    if not recent_values and not prior_values:
        return None
    return _trend(sum(recent_values), sum(prior_values))


def _weighted_position(rows: list[dict]) -> float | None:
    weighted = [(r["avg_position"], r["impressions"]) for r in rows if r.get("avg_position") is not None and r.get("impressions")]
    total_impressions = sum(impressions for _, impressions in weighted)
    if total_impressions == 0:
        return None
    return round(sum(position * impressions for position, impressions in weighted) / total_impressions, 2)


def compute_summary(rows: list[dict], today: date) -> dict:
    """Recent 7 days vs the 7 before, from traffic_daily-shaped dicts (metric_date, clicks, ...)."""
    anchor = today - timedelta(days=GSC_LAG_DAYS)
    recent_start = anchor - timedelta(days=WINDOW_DAYS - 1)
    prior_start = anchor - timedelta(days=2 * WINDOW_DAYS - 1)
    recent_rows = [r for r in rows if recent_start <= r["metric_date"] <= anchor]
    prior_rows = [r for r in rows if prior_start <= r["metric_date"] < recent_start]
    return {
        "clicks": _sum_trend(recent_rows, prior_rows, "clicks"),
        "impressions": _sum_trend(recent_rows, prior_rows, "impressions"),
        "sessions": _sum_trend(recent_rows, prior_rows, "sessions"),
        "position": {"recent": _weighted_position(recent_rows), "prior": _weighted_position(prior_rows)},
    }
