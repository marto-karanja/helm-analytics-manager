import gzip

import pytest

from app.indexing import classify as rules
from app.indexing import inspection as inspection_api
from app.indexing.signals import parse_html
from app.indexing.sitemap import SitemapParseError, parse_sitemap, robots_sitemaps, same_site, walk_sitemaps

URLSET = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc><lastmod>2026-09-01T10:00:00+00:00</lastmod></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>"""

INDEX = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/posts.xml</loc></sitemap>
  <sitemap><loc>https://example.com/pages.xml.gz</loc></sitemap>
  <sitemap><loc>https://evil.example.net/steal.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset_with_and_without_lastmod():
    parsed = parse_sitemap(URLSET)
    assert parsed.kind == "urlset"
    assert [e.loc for e in parsed.entries] == ["https://example.com/a", "https://example.com/b"]
    assert parsed.entries[0].lastmod.year == 2026 and parsed.entries[1].lastmod is None


def test_parse_index_and_gzip():
    assert parse_sitemap(INDEX).kind == "index"
    assert parse_sitemap(gzip.compress(URLSET)).kind == "urlset"


@pytest.mark.parametrize(
    "body",
    [b"<urlset><url>", b"not xml at all", b"<html><body/></html>", b"\x1f\x8bgarbage", b""],
)
def test_malformed_input_raises_a_parse_error(body):
    with pytest.raises(SitemapParseError):
        parse_sitemap(body)


def test_entity_expansion_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><urlset>&b;</urlset>'
    with pytest.raises(SitemapParseError):
        parse_sitemap(bomb)


def test_robots_sitemap_lines():
    robots = "User-agent: *\nDisallow: /x\nSitemap: https://example.com/s.xml\nsitemap:https://example.com/t.xml\n"
    assert robots_sitemaps(robots) == ["https://example.com/s.xml", "https://example.com/t.xml"]


def test_same_site_ignores_www_but_not_other_hosts():
    assert same_site("https://www.example.com/x", "https://example.com/")
    assert not same_site("https://evil.example.net/x", "https://example.com/")


def _fetcher(files: dict[str, bytes]):
    calls = []

    def fetch(url):
        calls.append(url)
        return files.get(url)

    fetch.calls = calls
    return fetch


def test_walk_follows_index_skips_offsite_and_reads_gzip():
    posts = URLSET
    pages = gzip.compress(
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/c</loc></url>'
        b"<url><loc>https://other.example.org/x</loc></url></urlset>"
    )
    fetch = _fetcher(
        {
            "https://example.com/robots.txt": b"Sitemap: https://example.com/sitemap_index.xml",
            "https://example.com/sitemap_index.xml": INDEX,
            "https://example.com/posts.xml": posts,
            "https://example.com/pages.xml.gz": pages,
        }
    )
    result = walk_sitemaps(fetch, "https://example.com/")
    assert sorted(result.urls) == ["https://example.com/a", "https://example.com/b", "https://example.com/c"]
    assert any("off-site" in e for e in result.errors)
    assert "https://evil.example.net/steal.xml" not in fetch.calls
    assert result.sitemaps_read == 3


def test_walk_falls_back_to_default_paths_and_reports_nothing_found():
    fetch = _fetcher({"https://example.com/sitemap.xml": URLSET})
    assert len(walk_sitemaps(fetch, "https://example.com/").urls) == 2
    empty = walk_sitemaps(_fetcher({}), "https://example.com/")
    assert empty.urls == {} and empty.errors == ["no sitemap found"]


def test_walk_survives_one_malformed_sitemap_and_loops():
    looping = b'<sitemapindex xmlns="x"><sitemap><loc>https://example.com/sitemap_index.xml</loc></sitemap><sitemap><loc>https://example.com/bad.xml</loc></sitemap><sitemap><loc>https://example.com/ok.xml</loc></sitemap></sitemapindex>'
    fetch = _fetcher(
        {
            "https://example.com/sitemap_index.xml": looping,
            "https://example.com/bad.xml": b"<oops",
            "https://example.com/ok.xml": URLSET,
        }
    )
    result = walk_sitemaps(fetch, "https://example.com/")
    assert len(result.urls) == 2
    assert any("bad.xml" in e for e in result.errors)


# ---------------------------------------------------------------- HTML signals

PAGE = """<html><head><title>  Best   Stalls </title>
<meta name="description" content="A guide"><link rel="canonical" href="/guide">
<script>var ignored = "words words words";</script><style>.x{}</style></head>
<body><h1>Guide</h1><p>One two three four five.</p><h2>First part</h2><h2>Second <b>part</b></h2>
<a href="/other">in</a><a href="https://example.com/other#frag">dup</a><a href="https://elsewhere.org/">out</a>
<noscript>hidden words</noscript></body></html>"""


def test_parse_html_extracts_signals():
    parsed = parse_html(PAGE, "https://example.com/guide")
    assert parsed.title == "Best Stalls"
    assert parsed.meta_description == "A guide"
    assert parsed.canonical == "https://example.com/guide"
    assert (parsed.h1_count, parsed.h2_count) == (1, 2)
    assert parsed.headings == ["First part", "Second part"]
    assert parsed.internal_links == 1  # the fragment variant is the same page; the external link is not counted
    assert parsed.word_count == 13  # script, style and noscript text excluded
    assert parsed.noindex is False and parsed.content_hash


def test_parse_html_detects_noindex_and_identical_hashes():
    a = parse_html('<html><head><meta name="robots" content="NOINDEX, follow"></head><body>same text</body></html>', "https://x.com/a")
    b = parse_html("<html><body>Same   TEXT</body></html>", "https://x.com/b")
    assert a.noindex is True and b.noindex is False
    assert a.content_hash == b.content_hash


def test_parse_html_empty_body_has_no_hash():
    parsed = parse_html("<html><body></body></html>", "https://x.com/")
    assert parsed.word_count == 0 and parsed.content_hash is None


# ---------------------------------------------------------------- classification


def _facts(url="https://example.com/p", **kw) -> rules.UrlFacts:
    base = dict(signals_fetched=True, http_status=200, word_count=800, title=f"T {url}", content_hash=url)
    base.update(kw)
    return rules.UrlFacts(url=url, **base)


def _issue(fact, others=(), thin=300):
    return rules.classify_all([fact, *others], thin)[fact.url]


@pytest.mark.parametrize(
    ("fact", "expected"),
    [
        (rules.UrlFacts(url="u"), rules.UNKNOWN),
        (_facts(http_status=404), rules.FETCH_ERROR),
        (_facts(http_status=None, fetch_error="Timeout"), rules.FETCH_ERROR),
        (_facts(inspected=True, page_fetch_state="SOFT_404", verdict="FAIL"), rules.FETCH_ERROR),
        (_facts(noindex=True), rules.BLOCKED),
        (_facts(inspected=True, robots_txt_state="DISALLOWED"), rules.BLOCKED),
        (_facts(inspected=True, indexing_state="BLOCKED_BY_META_TAG"), rules.BLOCKED),
        (_facts(canonical="https://example.com/other"), rules.BLOCKED),
        (_facts(canonical="https://EXAMPLE.com/p/"), rules.UNKNOWN),  # self-canonical, never inspected
        (_facts(word_count=120), rules.THIN),
        (_facts(inspected=True, verdict="NEUTRAL", coverage_state="Crawled - currently not indexed"), rules.CRAWLED_NOT_INDEXED),
        (_facts(inspected=True, verdict="NEUTRAL", coverage_state="Discovered - currently not indexed"), rules.DISCOVERED_NOT_INDEXED),
        (_facts(inspected=True, verdict="NEUTRAL", coverage_state="URL is unknown to Google"), rules.DISCOVERED_NOT_INDEXED),
        (_facts(inspected=True, verdict="PASS", coverage_state="Submitted and indexed"), rules.INDEXED),
    ],
)
def test_each_issue_label(fact, expected):
    assert _issue(fact) == expected


def test_first_match_wins_over_later_rules():
    thin_and_crawled = _facts(word_count=50, inspected=True, coverage_state="Crawled - currently not indexed")
    assert _issue(thin_and_crawled) == rules.THIN
    blocked_and_thin = _facts(noindex=True, word_count=50)
    assert _issue(blocked_and_thin) == rules.BLOCKED


def test_duplicates_by_hash_and_by_title():
    a = _facts("https://e.com/a", content_hash="h", title="One")
    b = _facts("https://e.com/b", content_hash="h", title="Two")
    c = _facts("https://e.com/c", title="  same   TITLE "), _facts("https://e.com/d", title="Same Title")
    unique = _facts("https://e.com/e")
    issues = rules.classify_all([a, b, *c, unique])
    assert issues["https://e.com/a"] == issues["https://e.com/b"] == rules.DUPLICATE_RISK
    assert issues["https://e.com/c"] == issues["https://e.com/d"] == rules.DUPLICATE_RISK
    assert issues["https://e.com/e"] == rules.UNKNOWN


def test_thin_threshold_is_configurable():
    fact = _facts(word_count=250)
    assert _issue(fact, thin=300) == rules.THIN
    assert _issue(fact, thin=200) == rules.UNKNOWN


# ---------------------------------------------------------------- inspection parsing and allocation


def test_parse_inspection_response():
    payload = {
        "inspectionResult": {
            "indexStatusResult": {
                "verdict": "NEUTRAL",
                "coverageState": "Crawled - currently not indexed",
                "robotsTxtState": "ALLOWED",
                "indexingState": "INDEXING_ALLOWED",
                "lastCrawlTime": "2026-09-30T08:15:00Z",
                "pageFetchState": "SUCCESSFUL",
                "googleCanonical": "https://example.com/p",
                "crawledAs": "MOBILE",
            }
        }
    }
    parsed = inspection_api.parse_inspection(payload)
    assert parsed["coverage_state"] == "Crawled - currently not indexed"
    assert parsed["last_crawl_time"].year == 2026 and parsed["crawled_as"] == "MOBILE"
    assert inspection_api.parse_inspection({})["verdict"] is None


def test_allocate_round_robins_so_a_big_site_cannot_starve_others():
    queues = {"big": [f"b{i}" for i in range(100)], "small": ["s0", "s1"], "mid": [f"m{i}" for i in range(10)]}
    chosen = inspection_api.allocate(queues, 9)
    per = {k: [u for p, u in chosen if p == k] for k in queues}
    assert (len(per["big"]), len(per["small"]), len(per["mid"])) == (4, 2, 3)  # small runs out after 2, its spare slot flows on
    assert chosen[:3] == [("big", "b0"), ("small", "s0"), ("mid", "m0")]


def test_allocate_respects_budget_ceiling_and_caps():
    queues = {"a": list(range(50)), "b": list(range(50))}
    assert len(inspection_api.allocate(queues, 0)) == 0
    assert len(inspection_api.allocate(queues, 1000)) == 100  # cannot exceed what exists
    capped = inspection_api.allocate(queues, 30, caps={"a": 5})
    assert sum(1 for p, _ in capped if p == "a") == 5 and len(capped) == 30
