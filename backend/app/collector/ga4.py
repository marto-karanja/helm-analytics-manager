from datetime import date

REQUEST_TIMEOUT_SECONDS = 60
URL = "https://analyticsdata.googleapis.com/v1beta/{property_id}:runReport"


def fetch_ga4_daily(session, property_id: str, start: date, end: date) -> list[dict]:
    body = {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "dimensions": [{"name": "date"}],
        "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}],
        "limit": 10000,
    }
    response = session.post(URL.format(property_id=property_id), json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return [
        {
            "metric_date": date.fromisoformat(_dashed(row["dimensionValues"][0]["value"])),
            # the Data API returns every metric value as a string
            "sessions": int(row["metricValues"][0]["value"]),
            "engaged_sessions": int(row["metricValues"][1]["value"]),
        }
        for row in response.json().get("rows", [])
    ]


def _dashed(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
