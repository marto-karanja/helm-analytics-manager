"""Page content signals: fetch the HTML and extract what the indexing classifier needs."""
import hashlib
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

USER_AGENT = "HelmIndexBot/1.0 (+https://helm.billtoolbox.com; own-site monitoring)"
FETCH_TIMEOUT_SECONDS = 20
MAX_BODY_BYTES = 3_000_000
MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST = 1.0

_SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)


@dataclass
class PageParse:
    title: str | None = None
    meta_description: str | None = None
    word_count: int = 0
    h1_count: int = 0
    h2_count: int = 0
    headings: list[str] = field(default_factory=list)
    internal_links: int = 0
    canonical: str | None = None
    noindex: bool = False
    content_hash: str | None = None


def _bare_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


class _Extractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.host = _bare_host(base_url)
        self.out = PageParse()
        self._title_parts: list[str] = []
        self._heading_parts: list[str] | None = None
        self._in_title = False
        self._body_text: list[str] = []
        self._in_body = False
        self._skip_depth = 0
        self._links: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "body":
            self._in_body = True
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = a.get("name", "").lower()
            content = a.get("content", "")
            if name == "description" and self.out.meta_description is None:
                self.out.meta_description = content.strip()
            if name in {"robots", "googlebot"} and "noindex" in content.lower():
                self.out.noindex = True
        elif tag == "link":
            if "canonical" in a.get("rel", "").lower().split() and a.get("href"):
                self.out.canonical = urljoin(self.base_url, a["href"].strip())
        elif tag == "a" and a.get("href"):
            target = urljoin(self.base_url, a["href"].strip())
            parts = urlsplit(target)
            if parts.scheme in {"http", "https"} and _bare_host(target) == self.host:
                self._links.add(parts._replace(fragment="").geturl())
        elif tag == "h1":
            self.out.h1_count += 1
        elif tag == "h2":
            self.out.h2_count += 1
            self._heading_parts = []

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        elif tag == "h2" and self._heading_parts is not None:
            text = " ".join("".join(self._heading_parts).split())
            if text:
                self.out.headings.append(text[:200])
            self._heading_parts = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        if self._heading_parts is not None:
            self._heading_parts.append(data)
        if self._in_body:
            self._body_text.append(data)

    def result(self) -> PageParse:
        self.out.title = " ".join("".join(self._title_parts).split()) or None
        words = _WORD.findall(" ".join(self._body_text))
        self.out.word_count = len(words)
        self.out.internal_links = len(self._links)
        normalised = " ".join(w.lower() for w in words)
        self.out.content_hash = hashlib.sha256(normalised.encode()).hexdigest() if words else None
        return self.out


def parse_html(html: str, url: str) -> PageParse:
    extractor = _Extractor(url)
    extractor.feed(html)
    extractor.close()
    return extractor.result()


@dataclass
class FetchedPage:
    url: str
    http_status: int | None
    html: str | None = None
    x_robots_noindex: bool = False
    final_url: str | None = None
    error: str | None = None


_last_request_at: dict[str, float] = {}


def _throttle(host: str) -> None:
    wait = _last_request_at.get(host, 0.0) + MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.monotonic()


def fetch_page(url: str, session=None) -> FetchedPage:
    """Plain HTTP fetch, rate-limited per host. Never raises: failures come back as `error`."""
    http = session or requests
    _throttle(urlsplit(url).netloc)
    try:
        response = http.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT_SECONDS, allow_redirects=True, stream=True
        )
        body = response.raw.read(MAX_BODY_BYTES + 1, decode_content=True)
        response.close()
    except requests.RequestException as exc:
        return FetchedPage(url=url, http_status=None, error=f"{type(exc).__name__}: {exc}"[:300])
    content_type = response.headers.get("Content-Type", "")
    is_html = "html" in content_type or not content_type
    html = body[:MAX_BODY_BYTES].decode(response.encoding or "utf-8", errors="replace") if is_html else None
    return FetchedPage(
        url=url,
        http_status=response.status_code,
        html=html,
        x_robots_noindex="noindex" in response.headers.get("X-Robots-Tag", "").lower(),
        final_url=response.url if response.url != url else None,
    )
