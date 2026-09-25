from datetime import date

import pytest
import requests

from app.collector.ga4 import fetch_ga4_daily
from app.collector.gsc import fetch_gsc_daily
from tests.fakes import FakeResponse, FakeSession

START, END = date(2026, 9, 1), date(2026, 9, 7)


def test_gsc_encodes_domain_property_and_sends_expected_body():
    session = FakeSession(lambda url, body: FakeResponse({"rows": []}))
    fetch_gsc_daily(session, "sc-domain:example.com", START, END)

    call = session.calls[0]
    assert call["url"] == (
        "https://searchconsole.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query"
    )
    assert call["json"] == {
        "startDate": "2026-09-01",
        "endDate": "2026-09-07",
        "dimensions": ["date"],
        "rowLimit": 25000,
    }
    assert call["kwargs"]["timeout"] > 0


def test_gsc_encodes_url_prefix_property():
    session = FakeSession(lambda url, body: FakeResponse({}))
    fetch_gsc_daily(session, "https://example.com/", START, END)
    assert "/sites/https%3A%2F%2Fexample.com%2F/searchAnalytics/query" in session.calls[0]["url"]


def test_gsc_parses_rows():
    payload = {
        "rows": [
            {"keys": ["2026-09-01"], "clicks": 12.0, "impressions": 340.0, "ctr": 0.0353, "position": 8.4},
            {"keys": ["2026-09-02"], "clicks": 0, "impressions": 5, "ctr": 0, "position": 30.1},
        ]
    }
    rows = fetch_gsc_daily(FakeSession(lambda u, b: FakeResponse(payload)), "sc-domain:example.com", START, END)
    assert rows == [
        {"metric_date": date(2026, 9, 1), "clicks": 12, "impressions": 340, "ctr": 0.0353, "avg_position": 8.4},
        {"metric_date": date(2026, 9, 2), "clicks": 0, "impressions": 5, "ctr": 0.0, "avg_position": 30.1},
    ]
    assert isinstance(rows[0]["clicks"], int)


def test_gsc_empty_response_returns_empty_list():
    assert fetch_gsc_daily(FakeSession(lambda u, b: FakeResponse({})), "sc-domain:example.com", START, END) == []


def test_gsc_http_error_propagates():
    session = FakeSession(lambda u, b: FakeResponse(status_code=403))
    with pytest.raises(requests.HTTPError):
        fetch_gsc_daily(session, "sc-domain:example.com", START, END)


def test_ga4_url_body_and_string_metric_parsing():
    payload = {
        "rows": [
            {
                "dimensionValues": [{"value": "20260901"}],
                "metricValues": [{"value": "120"}, {"value": "90"}],
            }
        ]
    }
    session = FakeSession(lambda url, body: FakeResponse(payload))
    rows = fetch_ga4_daily(session, "properties/123456789", START, END)

    call = session.calls[0]
    assert call["url"] == "https://analyticsdata.googleapis.com/v1beta/properties/123456789:runReport"
    assert call["json"] == {
        "dateRanges": [{"startDate": "2026-09-01", "endDate": "2026-09-07"}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}],
        "limit": 10000,
    }
    assert rows == [{"metric_date": date(2026, 9, 1), "sessions": 120, "engaged_sessions": 90}]


def test_ga4_empty_response_returns_empty_list():
    assert fetch_ga4_daily(FakeSession(lambda u, b: FakeResponse({})), "properties/1", START, END) == []


def test_ga4_http_error_propagates():
    session = FakeSession(lambda u, b: FakeResponse(status_code=500))
    with pytest.raises(requests.HTTPError):
        fetch_ga4_daily(session, "properties/1", START, END)
