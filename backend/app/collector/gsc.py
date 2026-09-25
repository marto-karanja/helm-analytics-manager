import urllib.parse
from datetime import date

REQUEST_TIMEOUT_SECONDS = 60
URL = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"


def fetch_gsc_daily(session, site_url: str, start: date, end: date) -> list[dict]:
    # site_url is `sc-domain:example.com` or `https://example.com/`; both need every reserved character encoded.
    url = URL.format(site=urllib.parse.quote(site_url, safe=""))
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["date"],
        "rowLimit": 25000,
    }
    response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return [
        {
            "metric_date": date.fromisoformat(row["keys"][0]),
            "clicks": int(row["clicks"]),
            "impressions": int(row["impressions"]),
            "ctr": float(row["ctr"]),
            "avg_position": float(row["position"]),
        }
        for row in response.json().get("rows", [])
    ]
