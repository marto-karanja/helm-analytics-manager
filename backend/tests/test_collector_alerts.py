import pytest

from app.collector.alerts import evaluate, overall_severity, pull_failed_alert


def _trend(recent: int, prior: int) -> dict:
    return {"recent": recent, "prior": prior, "pct_change": round((recent - prior) / prior * 100, 1) if prior else None}


def _summary(clicks=None, impressions=None, sessions=None, position=(None, None)) -> dict:
    return {
        "clicks": clicks,
        "impressions": impressions,
        "sessions": sessions,
        "position": {"recent": position[0], "prior": position[1]},
    }


@pytest.mark.parametrize(
    "recent, prior, expected",
    [
        (100, 100, []),
        (86, 100, []),  # -14%
        (85, 100, ["yellow"]),  # -15% is inclusive
        (66, 100, ["yellow"]),  # -34%
        (65, 100, ["red"]),  # -35% is inclusive
        (0, 100, ["red"]),
        (150, 100, []),
        (2, 29, []),  # big drop on tiny volume: below MIN_PRIOR_CLICKS
        (14, 30, ["red"]),  # exactly MIN_PRIOR_CLICKS is evaluated
    ],
)
def test_clicks_thresholds_and_volume_guard(recent, prior, expected):
    alerts = evaluate(_summary(clicks=_trend(recent, prior)))
    assert [a["severity"] for a in alerts] == expected


def test_clicks_message():
    (alert,) = evaluate(_summary(clicks=_trend(60, 100)))
    assert alert["message"] == "Organic clicks down 40% week-over-week"


def test_zero_impressions_is_red():
    (alert,) = evaluate(_summary(impressions=_trend(0, 500)))
    assert alert == {
        "severity": "red",
        "message": "Zero search impressions in the last 7 days (possible deindexing)",
    }


def test_zero_impressions_needs_a_prior_week():
    assert evaluate(_summary(impressions=_trend(0, 0))) == []


@pytest.mark.parametrize(
    "recent, prior, prior_impressions, expected",
    [
        (13.0, 10.0, 1000, []),  # exactly 3 worse is not "more than 3"
        (13.1, 10.0, 1000, ["yellow"]),
        (5.0, 10.0, 1000, []),  # improved
        (20.0, 10.0, 99, []),  # too few impressions to trust the average
        (None, 10.0, 1000, []),
    ],
)
def test_position_worsening(recent, prior, prior_impressions, expected):
    summary = _summary(impressions=_trend(500, prior_impressions), position=(recent, prior))
    assert [a["severity"] for a in evaluate(summary)] == expected


def test_tracking_broken_rule():
    summary = _summary(clicks=_trend(50, 50), sessions=_trend(0, 40))
    (alert,) = evaluate(summary)
    assert alert["severity"] == "yellow"
    assert alert["message"] == "GA4 shows no sessions while Search Console shows clicks (tracking tag may be broken)"


@pytest.mark.parametrize(
    "clicks, sessions",
    [
        (_trend(0, 50), _trend(0, 40)),  # no clicks either: not suspicious
        (_trend(50, 50), _trend(10, 40)),  # sessions exist
        (_trend(50, 50), None),  # GA4 not collected
        (None, _trend(0, 40)),  # GSC not collected
    ],
)
def test_tracking_broken_rule_stays_quiet(clicks, sessions):
    alerts = [a for a in evaluate(_summary(clicks=clicks, sessions=sessions)) if "tracking" in a["message"]]
    assert alerts == []


def test_pull_failed_alert_truncates_error():
    alert = pull_failed_alert("x" * 1000)
    assert alert["severity"] == "yellow"
    assert alert["message"].startswith("Traffic pull failed: xxx")
    assert len(alert["message"]) < 260


@pytest.mark.parametrize(
    "severities, expected",
    [([], "green"), (["yellow"], "yellow"), (["yellow", "red"], "red"), (["red", "yellow"], "red")],
)
def test_overall_severity(severities, expected):
    assert overall_severity([{"severity": s, "message": ""} for s in severities]) == expected
