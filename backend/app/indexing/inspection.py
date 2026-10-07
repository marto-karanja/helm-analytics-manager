"""Search Console URL Inspection API client and the daily-budget allocator."""
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TypeVar

INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
REQUEST_TIMEOUT_SECONDS = 60
# Google allows about 600 per minute per property; stay well under it.
MIN_SECONDS_BETWEEN_CALLS = 0.25
# Google documents about 2,000 inspections per property per day. Verify against current docs when tuning.
PER_PROPERTY_DAILY_QUOTA = 2000
MIN_REINSPECT_DAYS = 3

T = TypeVar("T")


class InspectionError(RuntimeError):
    pass


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_inspection(payload: dict) -> dict:
    status = (payload.get("inspectionResult") or {}).get("indexStatusResult") or {}
    return {
        "verdict": status.get("verdict"),
        "coverage_state": status.get("coverageState"),
        "indexing_state": status.get("indexingState"),
        "robots_txt_state": status.get("robotsTxtState"),
        "page_fetch_state": status.get("pageFetchState"),
        "last_crawl_time": _parse_time(status.get("lastCrawlTime")),
        "crawled_as": status.get("crawledAs"),
        "google_canonical": status.get("googleCanonical"),
    }


_last_call = 0.0


def inspect_url(session, site_url: str, url: str) -> dict:
    """One inspection. `session` is an AuthorizedSession; raises InspectionError with the HTTP status on failure."""
    global _last_call
    wait = _last_call + MIN_SECONDS_BETWEEN_CALLS - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    response = session.post(
        INSPECT_URL, json={"inspectionUrl": url, "siteUrl": site_url}, timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code >= 400:
        raise InspectionError(f"HTTP {response.status_code}")
    return parse_inspection(response.json())


def allocate(queues: dict[str, Sequence[T]], budget: int, caps: dict[str, int] | None = None) -> list[tuple[str, T]]:
    """Round-robin `budget` slots across projects so one large site cannot starve the others.

    `queues` maps project key to its URLs in priority order; `caps` maps project key to the most it may
    receive (the per-project split and the per-property quota). Unused capacity of a short queue flows on
    to the projects that still have URLs.
    """
    caps = caps or {}
    taken = {key: 0 for key in queues}
    chosen: list[tuple[str, T]] = []
    progressed = True
    while len(chosen) < budget and progressed:
        progressed = False
        for key, queue in queues.items():
            if len(chosen) >= budget:
                break
            if taken[key] < len(queue) and taken[key] < caps.get(key, PER_PROPERTY_DAILY_QUOTA):
                chosen.append((key, queue[taken[key]]))
                taken[key] += 1
                progressed = True
    return chosen
