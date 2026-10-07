import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, update

from app.core import app_settings
from app.core.config import settings
from app.db.session import async_session_maker
from app.keywords import export as export_mod
from app.keywords import generator, queries, rollup, scoring
from app.keywords import llm as llm_mod
from app.keywords import planner as planner_mod
from app.models.indexing import (
    AppSetting,
    GscQueryRollup,
    KeywordCandidate,
    KeywordMetric,
    KeywordRun,
    LlmSpend,
    PageSignal,
    SitemapUrl,
    WeeklyDigest,
)
from app.models.project import Project
from tests.fakes import FakeResponse, FakeSession

TODAY = date(2026, 10, 3)  # a Saturday; the last complete week starts Monday 2026-09-21
WEEK = date(2026, 9, 21)


@pytest_asyncio.fixture(autouse=True)
async def isolated():
    async with async_session_maker() as db:
        await db.execute(update(Project).values(is_pipeline=False))
        for model in (AppSetting, KeywordCandidate, KeywordRun, KeywordMetric, LlmSpend, GscQueryRollup, WeeklyDigest, PageSignal, SitemapUrl):
            await db.execute(delete(model))
        await db.commit()


async def make_project(**kw) -> Project:
    async with async_session_maker() as db:
        project = Project(
            slug=f"kw-{uuid.uuid4().hex[:8]}", name="KW Site", category="seo-content-site", url="https://kw.example/",
            is_pipeline=True, gsc_site_url="https://kw.example/", goals="Teach people about stalls", **kw,
        )
        db.add(project)
        await db.commit()
        return project


async def seed_rollups(project, rows):
    """rows: (query, page, impressions, position, clicks) in the last complete week."""
    async with async_session_maker() as db:
        for query, page, impressions, position, clicks in rows:
            db.add(GscQueryRollup(project_id=project.id, week_start=WEEK, query=query, page=page, impressions=impressions, position_avg=position, clicks=clicks))
        await db.commit()


# ---------------------------------------------------------------- scoring


def test_normalise_keyword():
    assert scoring.normalise_keyword("  How to Start a Stall?! ") == "how to start a stall"
    assert scoring.normalise_keyword("Mama's  kitchen-ideas") == "mama's kitchen-ideas"


def test_visibility_and_estimated_searches():
    assert scoring.visibility(3) == 1.0 and scoring.visibility(15) == 0.25 and scoring.visibility(25) == 0.08 and scoring.visibility(60) == 0.03
    assert scoring.estimate_monthly_searches(100, 5) == 100
    assert scoring.estimate_monthly_searches(100, 15) == 400  # page two: only a quarter of searchers get there
    assert scoring.estimate_monthly_searches(0, 15) == 0.0


def test_striking_distance_bounds():
    assert scoring.is_striking_distance(8, 10) and scoring.is_striking_distance(20, 10)
    assert not scoring.is_striking_distance(7.9, 100) and not scoring.is_striking_distance(20.1, 100)
    assert not scoring.is_striking_distance(12, 9) and not scoring.is_striking_distance(None, 100)


@pytest.mark.parametrize(
    ("avg", "monthly", "expected"),
    [(1000, None, True), (10, None, True), (1234, [1200, 1250] * 3, False), (500, [1000] * 12, True), (None, None, False), (0, [0] * 12, False)],
)
def test_bucket_heuristic(avg, monthly, expected):
    assert scoring.looks_like_bucket(avg, monthly) is expected


def test_resolve_demand_prefers_exact_planner_then_gsc_then_bucket():
    assert scoring.resolve_demand(400, 2000, False) == (2000.0, scoring.KP_EXACT)
    assert scoring.resolve_demand(5000, 2000, False) == (5000.0, scoring.KP_EXACT)  # GSC saw more than the planner reports
    assert scoring.resolve_demand(400, 1000, True) == (400, scoring.GSC)
    assert scoring.resolve_demand(None, 1000, True) == (1000.0, scoring.KP_BUCKET)
    assert scoring.resolve_demand(None, None, False) == (None, scoring.NONE)


def test_gap_classification():
    assert scoring.classify_gap(None, None, has_page=False) == "no_page"
    assert scoring.classify_gap(12, 50, True) == "striking_distance"
    assert scoring.classify_gap(3, 500, True) == "ranking"
    assert scoring.classify_gap(40, 500, True) == "other"


W = {"demand": 1.0, "gap": 1.2, "relevance": 0.6, "competition": 0.3}


def test_score_orders_striking_distance_above_ranking_and_discounts_weak_data():
    striking = scoring.score_candidate(2000, "striking_distance", 0.8, None, scoring.GSC, W)
    ranking = scoring.score_candidate(2000, "ranking", 0.8, None, scoring.GSC, W)
    assert striking > ranking
    assert scoring.score_candidate(2000, "no_page", 0.8, None, scoring.NONE, W) < scoring.score_candidate(2000, "no_page", 0.8, None, scoring.GSC, W)
    assert scoring.score_candidate(100_000, "striking_distance", 1, 0, scoring.GSC, W) <= 100
    assert scoring.score_candidate(None, "other", None, None, scoring.NONE, W) >= 0
    assert scoring.score_candidate(5000, "no_page", 0.5, 0.1, scoring.KP_EXACT, W) > scoring.score_candidate(5000, "no_page", 0.5, 0.9, scoring.KP_EXACT, W)


def test_demand_score_is_log_scaled_and_capped():
    assert scoring.demand_score(None) == 0 and scoring.demand_score(0) == 0
    assert scoring.demand_score(10_000_000) == 1.0
    assert 0 < scoring.demand_score(100) < scoring.demand_score(1000) < 1


# ---------------------------------------------------------------- rollup


def test_aggregate_weekly_weights_position_by_impressions():
    rows = [
        {"keys": ["q", "https://a/", "2026-09-21"], "clicks": 1, "impressions": 10, "position": 5.0},
        {"keys": ["q", "https://a/", "2026-09-23"], "clicks": 3, "impressions": 30, "position": 9.0},
        {"keys": ["q", "https://a/", "2026-09-28"], "clicks": 0, "impressions": 5, "position": 20.0},
    ]
    weekly = {r["week_start"]: r for r in rollup.aggregate_weekly(rows)}
    first = weekly[date(2026, 9, 21)]
    assert (first["clicks"], first["impressions"], first["position_avg"]) == (4, 40, 8.0)
    assert weekly[date(2026, 9, 28)]["impressions"] == 5


def test_fetch_pages_until_a_short_page(monkeypatch):
    monkeypatch.setattr(rollup, "ROW_LIMIT", 2)
    pages = [[{"keys": ["a", "p", "2026-09-21"]}] * 2, [{"keys": ["b", "p", "2026-09-21"]}]]

    def respond(url, body):
        return FakeResponse({"rows": pages[body["startRow"] // 2]})

    session = FakeSession(respond)
    rows = rollup.fetch_gsc_query_rows(session, "https://x/", date(2026, 9, 1), date(2026, 9, 30))
    assert len(rows) == 3 and [c["json"]["startRow"] for c in session.calls] == [0, 2]
    assert session.calls[0]["json"]["dimensions"] == ["query", "page", "date"]


async def test_rollup_job_stores_weekly_rows_and_a_digest():
    project = await make_project()

    def respond(url, body):
        return FakeResponse(
            {
                "rows": [
                    {"keys": ["best stalls", "https://kw.example/a", "2026-09-22"], "clicks": 2, "impressions": 40, "ctr": 0.05, "position": 9.0},
                    {"keys": ["best stalls", "https://kw.example/a", "2026-09-23"], "clicks": 1, "impressions": 40, "ctr": 0.02, "position": 11.0},
                ]
            }
        )

    result = await rollup.run_gsc_query_rollup(async_session_maker, FakeSession(respond), today=TODAY)
    assert result["status"] == "ok"
    async with async_session_maker() as db:
        row = (await db.execute(select(GscQueryRollup).where(GscQueryRollup.project_id == project.id))).scalar_one()
        assert (row.week_start, row.impressions, row.position_avg) == (WEEK, 80, 10.0)
        digest = (await db.execute(select(WeeklyDigest).where(WeeklyDigest.project_id == project.id))).scalar_one()
    assert digest.week_start == WEEK and digest.payload["top_queries"][0] == {"query": "best stalls", "clicks": 3, "impressions": 80}
    assert digest.payload["striking_distance"] == 1


async def test_rollup_failure_for_one_project_is_recorded_not_raised():
    project = await make_project()
    result = await rollup.run_gsc_query_rollup(async_session_maker, FakeSession(lambda u, b: FakeResponse(status_code=403)), today=TODAY)
    assert result["status"] == "error" and project.slug in result["detail"]


# ---------------------------------------------------------------- query reads


async def test_query_stats_exclude_the_current_partial_week_and_merge_case_variants():
    project = await make_project()
    await seed_rollups(project, [("Best Stalls", "https://kw.example/a", 60, 10.0, 3), ("best stalls", "https://kw.example/b", 40, 20.0, 1)])
    async with async_session_maker() as db:
        db.add(GscQueryRollup(project_id=project.id, week_start=date(2026, 9, 28), query="current week", page="p", impressions=999, position_avg=1, clicks=9))
        await db.commit()
        stats = await queries.query_stats(db, project.id, today=TODAY)
    assert {s.query for s in stats} == {"Best Stalls", "best stalls"}  # the in-progress week is not counted
    merged = queries.by_normalised_query(stats)["best stalls"]
    assert merged.impressions == 100 and merged.position == 14.0 and merged.top_page == "https://kw.example/a"
    assert [s.query for s in queries.cannibalised(stats, min_impressions=10)] == []  # each spelling has one page


async def test_cannibalisation_and_striking_lists():
    project = await make_project()
    await seed_rollups(project, [("q", "https://kw.example/a", 60, 10.0, 3), ("q", "https://kw.example/b", 40, 12.0, 1), ("top", "https://kw.example/a", 500, 2.0, 80)])
    async with async_session_maker() as db:
        stats = await queries.query_stats(db, project.id, today=TODAY)
    assert [s.query for s in queries.cannibalised(stats)] == ["q"]
    assert [s.query for s in queries.striking_distance(stats)] == ["q"]


# ---------------------------------------------------------------- planner


class FakeAds:
    def __init__(self, fail_after=None):
        self.calls = []
        self.fail_after = fail_after

    def post(self, url, json=None, headers=None, data=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if "oauth2" in url:
            return FakeResponse({"access_token": "tok", "expires_in": 3600})
        if self.fail_after is not None and len([c for c in self.calls if "oauth2" not in c["url"]]) > self.fail_after:
            return FakeResponse(status_code=500)
        return FakeResponse(
            {
                "results": [
                    {"text": kw, "keywordMetrics": {"avgMonthlySearches": "1300", "competitionIndex": "40", "monthlySearchVolumes": [{"year": 2026, "month": "JANUARY", "monthlySearches": "1300"}]}}
                    for kw in (json.get("keywords") or ["idea"])
                ]
            }
        )


@pytest.fixture
def ads_configured(monkeypatch):
    for name in ("google_ads_developer_token", "google_ads_client_id", "google_ads_client_secret", "google_ads_refresh_token", "google_ads_customer_id"):
        monkeypatch.setattr(settings, name, "x" if name != "google_ads_customer_id" else "1234567890")
    monkeypatch.setattr(settings, "google_ads_login_customer_id", "999")


async def test_planner_lookup_caches_and_sends_the_right_request(ads_configured):
    http = FakeAds()
    client = planner_mod.PlannerClient(http=http)
    assert client.configured
    async with async_session_maker() as db:
        found = await planner_mod.lookup(db, client, ["Best Stalls", "market rent"])
        assert found["best stalls"].avg_monthly_searches == 1300 and found["best stalls"].competition_index == 0.4 and not found["best stalls"].is_bucket
        api_calls = [c for c in http.calls if "oauth2" not in c["url"]]
        assert len(api_calls) == 1
        call = api_calls[0]
        assert call["url"].endswith("/customers/1234567890:generateKeywordHistoricalMetrics")
        assert call["headers"]["developer-token"] == "x" and call["headers"]["login-customer-id"] == "999"
        assert call["json"]["geoTargetConstants"] == ["geoTargetConstants/2404"] and call["json"]["language"] == "languageConstants/1000"

        again = await planner_mod.lookup(db, client, ["best stalls", "market rent"])
        assert len([c for c in http.calls if "oauth2" not in c["url"]]) == 1  # served from the quarterly cache
        assert again["market rent"].avg_monthly_searches == 1300


async def test_planner_cache_expires_after_90_days_and_failures_are_contained(ads_configured):
    async with async_session_maker() as db:
        db.add(KeywordMetric(keyword="old", geo="2404", language="1000", provider=planner_mod.PROVIDER, avg_monthly_searches=5, fetched_at=datetime.now(timezone.utc) - timedelta(days=120)))
        await db.commit()
        client = planner_mod.PlannerClient(http=FakeAds(fail_after=0))
        found = await planner_mod.lookup(db, client, ["old", "new"])
    assert found == {}  # the stale row is ignored and the failed API call returns nothing, without raising


async def test_planner_unconfigured_returns_only_the_cache(monkeypatch):
    monkeypatch.setattr(settings, "google_ads_developer_token", "")
    client = planner_mod.PlannerClient(http=FakeAds())
    assert not client.configured
    async with async_session_maker() as db:
        assert await planner_mod.lookup(db, client, ["anything"]) == {}


def test_planner_ideas_request_shapes(ads_configured):
    http = FakeAds()
    client = planner_mod.PlannerClient(http=http)
    client.keyword_ideas(seeds=["a"] * 30, url="https://competitor.example/page")
    body = http.calls[-1]["json"]
    assert len(body["keywordAndUrlSeed"]["keywords"]) == 20 and body["keywordAndUrlSeed"]["url"].startswith("https://competitor")
    client.keyword_ideas(url="https://competitor.example/page")
    assert "urlSeed" in http.calls[-1]["json"]
    with pytest.raises(planner_mod.PlannerError):
        client.keyword_ideas()


# ---------------------------------------------------------------- generator


def fake_llm(clusters, cost_tokens=(1000, 500)):
    calls = []

    async def call(system, user, schema):
        calls.append({"system": system, "user": user, "schema": schema})
        return llm_mod.LlmReply(text=json.dumps({"clusters": clusters}), model="claude-opus-5-5", input_tokens=cost_tokens[0], output_tokens=cost_tokens[1])

    call.calls = calls
    return call


CLUSTERS = [
    {"label": "Starting a stall", "intent": "informational", "keywords": [{"keyword": "How to start a stall?", "relevance": 0.9}, {"keyword": "stall permit kenya", "relevance": 0.8}]},
    {"label": "Buying", "intent": "commercial", "keywords": [{"keyword": "best stall tents", "relevance": 0.7}, {"keyword": "how to start a stall", "relevance": 0.9}]},
]


async def run(project, llm, planner=None, **kw):
    async with async_session_maker() as db:
        run_row = await generator.start_run(db, project.id)
    return await generator.execute_run(async_session_maker, run_row.id, llm=llm, planner=planner or planner_mod.PlannerClient(http=FakeAds()), **kw)


async def candidates(project) -> dict[str, KeywordCandidate]:
    async with async_session_maker() as db:
        rows = (await db.execute(select(KeywordCandidate).where(KeywordCandidate.project_id == project.id))).scalars()
        return {r.keyword: r for r in rows}


async def test_generator_combines_gsc_striking_distance_with_llm_candidates():
    project = await make_project()
    async with async_session_maker() as db:
        db.add(PageSignal(project_id=project.id, url="https://kw.example/permits", http_status=200, title="Stall permit Kenya guide", word_count=900))
        await db.commit()

    result = await run(project, fake_llm(CLUSTERS))
    assert result.status == "ok", result.error
    assert result.model == "claude-opus-5-5" and result.cost_usd == pytest.approx(0.014)  # 1000*4/1M + 500*20/1M
    assert result.source_counts["gsc_striking"] == 0
    found = await candidates(project)
    assert "how to start a stall" in found and "best stall tents" in found
    assert len([k for k in found if k == "how to start a stall"]) == 1  # normalised duplicate across clusters dropped
    permit = found["stall permit kenya"]
    assert permit.target_url == "https://kw.example/permits" and permit.gap == "other"  # an existing page covers it: improve, not new
    assert found["best stall tents"].gap == "no_page" and found["best stall tents"].demand_source == "none"
    assert found["best stall tents"].status == "proposed" and found["best stall tents"].intent == "commercial"
    async with async_session_maker() as db:
        assert (await db.execute(select(func.count()).select_from(LlmSpend))).scalar_one() == 1


async def test_generator_striking_candidates_use_the_rolled_up_window(monkeypatch):
    project = await make_project()
    today = date.today()
    last_week = rollup.week_start(today) - timedelta(days=7)
    async with async_session_maker() as db:
        for q, page, impr, pos in (("stall rent nairobi", "https://kw.example/rent", 200, 11.0), ("top query", "https://kw.example/top", 900, 2.0)):
            db.add(GscQueryRollup(project_id=project.id, week_start=last_week, query=q, page=page, impressions=impr, position_avg=pos, clicks=5))
        await db.commit()
    result = await run(project, fake_llm([]))
    assert result.status == "ok" and result.source_counts["gsc_striking"] == 1
    found = await candidates(project)
    c = found["stall rent nairobi"]
    assert (c.source, c.gap, c.demand_source, c.target_url) == ("gsc", "striking_distance", "gsc", "https://kw.example/rent")
    assert c.demand_est == 800.0  # 200 impressions at position 11 -> a quarter of searchers reach page two
    assert c.score > 0 and "top query" not in found  # already ranking well: not a striking-distance candidate


async def test_rerun_refreshes_numbers_but_never_overrides_a_decision():
    project = await make_project()
    await run(project, fake_llm(CLUSTERS))
    async with async_session_maker() as db:
        row = (await db.execute(select(KeywordCandidate).where(KeywordCandidate.project_id == project.id, KeywordCandidate.keyword == "best stall tents"))).scalar_one()
        row.status, row.decided_at = "accepted", datetime.now(timezone.utc)
        await db.commit()
    llm = fake_llm([{"label": "Buying", "intent": "commercial", "keywords": [{"keyword": "best stall tents", "relevance": 0.4}, {"keyword": "stall lighting", "relevance": 0.6}]}])
    again = await run(project, llm)
    found = await candidates(project)
    assert found["best stall tents"].status == "accepted"
    assert "best stall tents" in llm.calls[0]["user"]  # already-known keywords are sent as "do not repeat"
    assert "stall lighting" in found and again.status == "ok"
    assert len(found) == 4


async def test_daily_cap_blocks_the_llm_call_and_marks_the_run_failed():
    project = await make_project()
    async with async_session_maker() as db:
        await app_settings.put_setting(db, "llm_daily_cap_usd", 1.0, "t")
        db.add(LlmSpend(model="claude-opus-5-5", cost_usd=1.5))
        await db.commit()
    llm = fake_llm(CLUSTERS)
    result = await run(project, llm)
    assert result.status == "error" and "cap reached" in result.error and llm.calls == []


async def test_llm_failure_marks_the_run_failed_with_the_reason():
    project = await make_project()

    async def refuses(system, user, schema):
        raise llm_mod.LlmError("the model declined the request (cyber)")

    result = await run(project, refuses)
    assert result.status == "error" and "declined" in result.error and result.finished_at is not None


async def test_second_run_is_refused_while_one_is_in_progress():
    project = await make_project()
    async with async_session_maker() as db:
        await generator.start_run(db, project.id)
        with pytest.raises(generator.GeneratorError):
            await generator.start_run(db, project.id)
        # a run stuck for over half an hour does not block forever
        await db.execute(update(KeywordRun).values(started_at=datetime.now(timezone.utc) - timedelta(hours=2)))
        await db.commit()
        await generator.start_run(db, project.id)


async def test_planner_volume_is_used_when_the_toggle_is_keyword_planner(ads_configured):
    project = await make_project()
    async with async_session_maker() as db:
        await app_settings.put_setting(db, "volume_source", "keyword_planner", "t")
    result = await run(project, fake_llm(CLUSTERS), planner=planner_mod.PlannerClient(http=FakeAds()))
    found = await candidates(project)
    assert result.source_counts["planner_metrics"] == 3
    c = found["best stall tents"]
    assert (c.volume, c.demand_source, c.competition) == (1300, "kp_exact", 0.4)


async def test_planner_toggle_without_credentials_is_noted_not_fatal(monkeypatch):
    monkeypatch.setattr(settings, "google_ads_developer_token", "")
    project = await make_project()
    async with async_session_maker() as db:
        await app_settings.put_setting(db, "volume_source", "keyword_planner", "t")
    result = await run(project, fake_llm(CLUSTERS))
    assert result.status == "ok" and result.source_counts["planner_skipped"] == "not configured"


def test_parse_llm_drafts_cleans_and_caps():
    drafts = generator.parse_llm_drafts(
        {"clusters": [{"label": "A", "intent": "bogus", "keywords": [{"keyword": "  ", "relevance": 1}, {"keyword": "x" * 300, "relevance": 1}, {"keyword": "ok one", "relevance": "high"}]}]}
    )
    assert [d.keyword for d in drafts] == ["ok one"] and drafts[0].intent is None and drafts[0].relevance is None
    many = {"clusters": [{"label": "B", "intent": "informational", "keywords": [{"keyword": f"kw {i}", "relevance": 0.5} for i in range(200)]}]}
    assert len(generator.parse_llm_drafts(many)) == generator.MAX_LLM_CANDIDATES


def test_cost_and_unknown_model_pricing():
    assert llm_mod.cost_usd("claude-opus-5-5", 1_000_000, 1_000_000) == 24.0
    assert llm_mod.cost_usd("some-future-model", 1_000_000, 0) == 10.0  # unknown models are priced at the top rate


async def test_call_claude_requires_a_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(llm_mod.LlmError):
        await llm_mod.call_claude("s", "u", {})


# ---------------------------------------------------------------- export


async def test_export_writes_the_queue_atomically_and_marks_written(tmp_path):
    project = await make_project()
    async with async_session_maker() as db:
        for kw, status, url in (("accepted new", "accepted", None), ("accepted improve", "accepted", "https://kw.example/p"), ("rejected one", "rejected", None), ("proposed one", "proposed", None)):
            db.add(KeywordCandidate(project_id=project.id, keyword=kw, status=status, target_url=url, score=10.0 if url is None else 20.0))
        await db.commit()
        result = await export_mod.export_queue(db, project, export_dir=str(tmp_path))
    assert result["count"] == 2
    queue = json.loads((tmp_path / project.slug / "keyword_queue.json").read_text(encoding="utf-8"))
    assert [k["keyword"] for k in queue["keywords"]] == ["accepted improve", "accepted new"]  # best score first
    assert [k["action"] for k in queue["keywords"]] == ["improve", "new_article"]
    assert list((tmp_path / project.slug).glob("*.tmp")) == []
    found = await candidates(project)
    assert found["accepted new"].status == "written" and found["proposed one"].status == "proposed"

    async with async_session_maker() as db:  # a re-export keeps already-written keywords in the file
        again = await export_mod.export_queue(db, project, export_dir=str(tmp_path))
    assert again["count"] == 2


async def test_export_without_a_directory_still_returns_the_payload(monkeypatch):
    monkeypatch.setattr(settings, "keyword_export_dir", "")
    project = await make_project()
    async with async_session_maker() as db:
        result = await export_mod.export_queue(db, project)
    assert result["path"] is None and result["payload"]["keywords"] == []


def test_export_rejects_path_traversal_slugs(tmp_path):
    bad = Project(slug="../../etc", name="x", category="c", url="u")
    with pytest.raises(ValueError):
        export_mod.write_queue_file(bad, {"keywords": []}, str(tmp_path))
