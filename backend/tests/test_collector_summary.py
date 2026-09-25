from datetime import date, timedelta

import pytest

from app.collector.summary import compute_summary

TODAY = date(2026, 9, 20)
ANCHOR = TODAY - timedelta(days=3)  # 2026-09-17


def _row(days_before_anchor: int, **values) -> dict:
    return {"metric_date": ANCHOR - timedelta(days=days_before_anchor), **values}


def test_windows_and_pct_change():
    rows = [_row(0, clicks=10), _row(6, clicks=10), _row(7, clicks=20), _row(13, clicks=20)]
    summary = compute_summary(rows, TODAY)
    assert summary["clicks"] == {"recent": 20, "prior": 40, "pct_change": -50.0}


@pytest.mark.parametrize(
    "days_before_anchor, bucket",
    [(-1, None), (0, "recent"), (6, "recent"), (7, "prior"), (13, "prior"), (14, None)],
)
def test_window_boundaries(days_before_anchor, bucket):
    summary = compute_summary([_row(days_before_anchor, clicks=7)], TODAY)
    if bucket is None:
        assert summary["clicks"] is None
    else:
        assert summary["clicks"][bucket] == 7


def test_pct_change_is_none_when_prior_is_zero():
    summary = compute_summary([_row(0, clicks=5), _row(7, clicks=0)], TODAY)
    assert summary["clicks"] == {"recent": 5, "prior": 0, "pct_change": None}


def test_pct_change_rounds_to_one_decimal():
    summary = compute_summary([_row(0, clicks=2), _row(7, clicks=3)], TODAY)
    assert summary["clicks"]["pct_change"] == -33.3


def test_source_without_data_is_none():
    summary = compute_summary([_row(0, clicks=5, impressions=50)], TODAY)
    assert summary["sessions"] is None
    assert summary["clicks"]["recent"] == 5


def test_no_rows_at_all():
    summary = compute_summary([], TODAY)
    assert summary["clicks"] is None and summary["sessions"] is None
    assert summary["position"] == {"recent": None, "prior": None}


def test_position_is_impression_weighted():
    rows = [
        _row(0, impressions=900, avg_position=2.0),
        _row(1, impressions=100, avg_position=12.0),
        _row(7, impressions=100, avg_position=10.0),
    ]
    position = compute_summary(rows, TODAY)["position"]
    assert position == {"recent": 3.0, "prior": 10.0}


def test_position_none_without_impressions():
    rows = [_row(0, impressions=0, avg_position=5.0)]
    assert compute_summary(rows, TODAY)["position"]["recent"] is None
