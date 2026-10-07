CLICKS_DROP_YELLOW = 15  # percent, week-over-week
CLICKS_DROP_RED = 35
# A 60% drop from 8 clicks to 3 is noise, not a trend.
MIN_PRIOR_CLICKS = 30
POSITION_WORSE_BY = 3
# Average position on a handful of impressions swings wildly.
MIN_PRIOR_IMPRESSIONS_FOR_POSITION = 100
MAX_ERROR_CHARS = 200

_ORDER = {"green": 0, "yellow": 1, "red": 2}


def evaluate(summary: dict, expect_data: bool = True) -> list[dict]:
    """Every alert carries a stable `kind`, which is what the alert-event state machine keys on.

    `expect_data=False` is for a project the owner marked as dormant: no rows is then not an alert.
    """
    alerts: list[dict] = []
    clicks = summary.get("clicks")
    impressions = summary.get("impressions")
    sessions = summary.get("sessions")
    position = summary.get("position") or {}

    if clicks is None and impressions is None and sessions is None:
        # A configured project with no rows at all is not "green": nothing has been measured.
        if expect_data:
            alerts.append({"kind": "no_data", "severity": "yellow", "message": "No traffic data collected for this project yet"})
        return alerts

    if clicks and clicks["pct_change"] is not None and clicks["prior"] >= MIN_PRIOR_CLICKS:
        pct = clicks["pct_change"]
        if pct <= -CLICKS_DROP_RED:
            alerts.append({"kind": "clicks_drop", "severity": "red", "message": f"Organic clicks down {abs(pct):.0f}% week-over-week"})
        elif pct <= -CLICKS_DROP_YELLOW:
            alerts.append({"kind": "clicks_drop", "severity": "yellow", "message": f"Organic clicks down {abs(pct):.0f}% week-over-week"})

    if impressions and impressions["recent"] == 0 and impressions["prior"] > 0:
        alerts.append(
            {
                "kind": "zero_impressions",
                "severity": "red",
                "message": "Zero search impressions in the last 7 days (possible deindexing)",
            }
        )

    recent_position, prior_position = position.get("recent"), position.get("prior")
    if (
        recent_position is not None
        and prior_position is not None
        and impressions
        and impressions["prior"] >= MIN_PRIOR_IMPRESSIONS_FOR_POSITION
        and recent_position - prior_position > POSITION_WORSE_BY
    ):
        alerts.append(
            {
                "kind": "position_worse",
                "severity": "yellow",
                "message": f"Average search position worsened from {prior_position:.1f} to {recent_position:.1f}",
            }
        )

    if sessions and sessions["recent"] == 0 and clicks and clicks["recent"] > 0:
        alerts.append(
            {
                "kind": "sessions_zero_clicks_nonzero",
                "severity": "yellow",
                "message": "GA4 shows no sessions while Search Console shows clicks (tracking tag may be broken)",
            }
        )

    return alerts


def pull_failed_alert(error: str) -> dict:
    return {"kind": "pull_failed", "severity": "yellow", "message": f"Traffic pull failed: {error[:MAX_ERROR_CHARS]}"}


def overall_severity(alerts: list[dict]) -> str:
    return max((a["severity"] for a in alerts), key=_ORDER.__getitem__, default="green")
