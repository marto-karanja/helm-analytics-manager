"""Sitemap discovery and parsing: robots.txt, sitemap indexes, nested sitemaps, gzip, malformed XML."""
import gzip
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from defusedxml import ElementTree as SafeET

logger = logging.getLogger("helm.indexing")

MAX_SITEMAPS = 200
MAX_URLS = 100_000
GZIP_MAGIC = b"\x1f\x8b"
DEFAULT_PATHS = ("/sitemap_index.xml", "/sitemap.xml")


class SitemapParseError(ValueError):
    pass


@dataclass
class SitemapEntry:
    loc: str
    lastmod: datetime | None = None


@dataclass
class ParsedSitemap:
    kind: str  # index | urlset
    entries: list[SitemapEntry]


@dataclass
class WalkResult:
    urls: dict[str, tuple[str, datetime | None]] = field(default_factory=dict)  # url -> (source_sitemap, lastmod)
    errors: list[str] = field(default_factory=list)
    sitemaps_read: int = 0


def parse_lastmod(text: str | None) -> datetime | None:
    if not text:
        return None
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def decode_body(body: bytes) -> bytes:
    """Sitemaps may be gzipped regardless of the Content-Type or the .gz suffix, so sniff the magic bytes."""
    if body[:2] == GZIP_MAGIC:
        try:
            return gzip.decompress(body)
        except (OSError, EOFError) as exc:
            raise SitemapParseError(f"bad gzip: {exc}") from exc
    return body


def parse_sitemap(body: bytes) -> ParsedSitemap:
    try:
        root = SafeET.fromstring(decode_body(body))
    except SitemapParseError:
        raise
    except Exception as exc:  # noqa: BLE001 -- ParseError, or defusedxml's entity/DTD refusals
        raise SitemapParseError(f"malformed XML: {exc}") from exc

    root_name = _local(root.tag)
    if root_name not in {"sitemapindex", "urlset"}:
        raise SitemapParseError(f"unexpected root element <{root_name}>")
    item_name = "sitemap" if root_name == "sitemapindex" else "url"

    entries: list[SitemapEntry] = []
    for item in root:
        if _local(item.tag) != item_name:
            continue
        loc = lastmod = None
        for child in item:
            name = _local(child.tag)
            if name == "loc":
                loc = (child.text or "").strip()
            elif name == "lastmod":
                lastmod = parse_lastmod(child.text)
        if loc:
            entries.append(SitemapEntry(loc=loc, lastmod=lastmod))
    return ParsedSitemap(kind="index" if root_name == "sitemapindex" else "urlset", entries=entries)


def robots_sitemaps(robots_txt: str) -> list[str]:
    found = []
    for line in robots_txt.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "sitemap" and value.strip():
            found.append(value.strip())
    return found


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, site_url: str) -> bool:
    """A sitemap index must not be able to steer the walker to other hosts."""
    return _host(url) == _host(site_url)


def walk_sitemaps(
    fetch: Callable[[str], bytes | None], site_url: str, extra_roots: list[str] | None = None
) -> WalkResult:
    """`fetch(url)` returns the body, or None for a 404. Other failures should raise."""
    origin = f"{urlsplit(site_url).scheme}://{urlsplit(site_url).netloc}"
    result = WalkResult()

    roots = list(extra_roots or [])
    try:
        robots = fetch(urljoin(origin, "/robots.txt"))
        if robots:
            roots += robots_sitemaps(robots.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 -- robots.txt is only a hint
        logger.info("robots.txt unavailable for %s: %s", origin, exc)
    if not roots:
        roots = [urljoin(origin, p) for p in DEFAULT_PATHS]

    queue = list(dict.fromkeys(roots))
    seen: set[str] = set()
    any_found = False
    while queue and result.sitemaps_read < MAX_SITEMAPS:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if not same_site(url, site_url):
            result.errors.append(f"skipped off-site sitemap {url}")
            continue
        try:
            body = fetch(url)
            if body is None:
                continue  # a missing default path is normal; only fail if nothing at all is found
            parsed = parse_sitemap(body)
        except Exception as exc:  # noqa: BLE001 -- one bad sitemap must not lose the others
            result.errors.append(f"{url}: {exc}"[:300])
            continue
        any_found = True
        result.sitemaps_read += 1
        if parsed.kind == "index":
            queue.extend(e.loc for e in parsed.entries)
            continue
        for entry in parsed.entries:
            if len(result.urls) >= MAX_URLS:
                result.errors.append(f"stopped at {MAX_URLS} URLs")
                return result
            if same_site(entry.loc, site_url):
                result.urls.setdefault(entry.loc, (url, entry.lastmod))
    if not any_found and not result.errors:
        result.errors.append("no sitemap found")
    return result
