"""Issue classification: one primary issue per URL, first match wins. Labels and rules live only here."""
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

FETCH_ERROR = "fetch_error"
BLOCKED = "blocked"
DUPLICATE_RISK = "duplicate_risk"
THIN = "thin"
CRAWLED_NOT_INDEXED = "crawled_not_indexed"
DISCOVERED_NOT_INDEXED = "discovered_not_indexed"
INDEXED = "indexed"
UNKNOWN = "unknown"  # never inspected and never fetched: nothing to say yet

ISSUES = (FETCH_ERROR, BLOCKED, DUPLICATE_RISK, THIN, CRAWLED_NOT_INDEXED, DISCOVERED_NOT_INDEXED, INDEXED, UNKNOWN)

DEFAULT_THIN_WORDS = 300

CRAWLED_STATE = "crawled - currently not indexed"
DISCOVERED_STATE = "discovered - currently not indexed"


@dataclass
class UrlFacts:
    url: str
    # latest page fetch
    http_status: int | None = None
    fetch_error: str | None = None
    noindex: bool = False
    canonical: str | None = None
    word_count: int | None = None
    title: str | None = None
    content_hash: str | None = None
    signals_fetched: bool = False
    # latest URL inspection
    inspected: bool = False
    verdict: str | None = None
    coverage_state: str | None = None
    indexing_state: str | None = None
    robots_txt_state: str | None = None
    page_fetch_state: str | None = None


def _norm_url(url: str) -> str:
    parts = urlsplit(url)
    return parts._replace(fragment="", netloc=parts.netloc.lower(), path=parts.path.rstrip("/") or "/").geturl()


def _norm_title(title: str | None) -> str | None:
    if not title:
        return None
    return " ".join(title.lower().split()) or None


def duplicate_urls(facts: list[UrlFacts]) -> set[str]:
    """URLs sharing a content hash or an identical normalised title with at least one other URL."""
    by_hash = Counter(f.content_hash for f in facts if f.content_hash)
    by_title = Counter(_norm_title(f.title) for f in facts if _norm_title(f.title))
    return {
        f.url
        for f in facts
        if (f.content_hash and by_hash[f.content_hash] > 1)
        or (_norm_title(f.title) and by_title[_norm_title(f.title)] > 1)
    }


def classify(fact: UrlFacts, duplicates: set[str], thin_words: int = DEFAULT_THIN_WORDS) -> str:
    if not fact.signals_fetched and not fact.inspected:
        return UNKNOWN

    page_fetch = (fact.page_fetch_state or "").upper()
    inspection_fetch_failed = fact.inspected and page_fetch not in {"", "SUCCESSFUL"}
    if fact.fetch_error or (fact.http_status is not None and fact.http_status != 200) or inspection_fetch_failed:
        return FETCH_ERROR

    robots_blocked = (fact.robots_txt_state or "").upper() == "DISALLOWED"
    indexing_blocked = (fact.indexing_state or "").upper() in {
        "BLOCKED_BY_META_TAG",
        "BLOCKED_BY_HTTP_HEADER",
        "BLOCKED_BY_ROBOTS_TXT",
    }
    canonical_elsewhere = bool(fact.canonical) and _norm_url(fact.canonical) != _norm_url(fact.url)
    if fact.noindex or robots_blocked or indexing_blocked or canonical_elsewhere:
        return BLOCKED

    if fact.url in duplicates:
        return DUPLICATE_RISK

    if fact.word_count is not None and fact.word_count < thin_words:
        return THIN

    state = (fact.coverage_state or "").strip().lower()
    if state == CRAWLED_STATE:
        return CRAWLED_NOT_INDEXED
    if state == DISCOVERED_STATE:
        return DISCOVERED_NOT_INDEXED

    if fact.inspected:
        # Only a PASS verdict means Google indexed it; any other answer (e.g. "URL is unknown to Google") does not.
        return INDEXED if (fact.verdict or "").upper() == "PASS" else DISCOVERED_NOT_INDEXED
    return UNKNOWN


def classify_all(facts: list[UrlFacts], thin_words: int = DEFAULT_THIN_WORDS) -> dict[str, str]:
    duplicates = duplicate_urls(facts)
    return {f.url: classify(f, duplicates, thin_words) for f in facts}
