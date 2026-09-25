import re
import urllib.parse
import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.collector.runner import run_once
from app.core.config import settings
from app.db.session import async_session_maker
from app.models.project import Project, TrafficDaily, TrafficSnapshot
from tests.fakes import FakeResponse, FakeSession

TODAY = date(2026, 9, 20)


def _days(start: str, end: str) -> list[date]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def google_fake(failing: str | None = None) -> FakeSession:
    """Answers both APIs for every requested day; raises an HTTP 403 for any URL containing `failing`."""

    def respond(url: str, body: dict) -> FakeResponse:
        if failing and failing in urllib.parse.unquote(url):
            return FakeResponse(status_code=403)
        if "searchconsole" in url:
            days = _days(body["startDate"], body["endDate"])
            return FakeResponse(
                {
                    "rows": [
                        {"keys": [d.isoformat()], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 8.0}
                        for d in days
                    ]
                }
            )
        window = body["dateRanges"][0]
        days = _days(window["startDate"], window["endDate"])
        return FakeResponse(
            {
                "rows": [
                    {
                        "dimensionValues": [{"value": d.strftime("%Y%m%d")}],
                        "metricValues": [{"value": "8"}, {"value": "6"}],
                    }
                    for d in days
                ]
            }
        )

    return FakeSession(respond)


@pytest_asyncio.fixture(autouse=True)
async def only_this_tests_projects_are_configured():
    """Other test modules leave projects with identifiers set in the shared test database."""
    async with async_session_maker() as session:
        await session.execute(update(Project).values(gsc_site_url=None, ga4_property_id=None))
        await session.commit()


async def _project(gsc: str | None = None, ga4: str | None = None, **extra) -> Project:
    async with async_session_maker() as session:
        project = Project(
            slug=f"collect-{uuid.uuid4()}", name="Collect", category="seo-content-site", url="https://x.example",
            is_pipeline=True, gsc_site_url=gsc, ga4_property_id=ga4, **extra,
        )
        session.add(project)
        await session.commit()
        return project


async def _count_days(project_id) -> int:
    async with async_session_maker() as session:
        return (
            await session.execute(select(func.count()).select_from(TrafficDaily).where(TrafficDaily.project_id == project_id))
        ).scalar_one()


async def _snapshots(project_id) -> list[TrafficSnapshot]:
    async with async_session_maker() as session:
        result = await session.execute(
            select(TrafficSnapshot).where(TrafficSnapshot.project_id == project_id).order_by(TrafficSnapshot.synced_at.desc())
        )
        return list(result.scalars().all())


async def test_ok_run_writes_rows_snapshot_and_run_record():
    project = await _project(gsc="sc-domain:ok.example", ga4="properties/1")

    run = await run_once(http_session=google_fake(), today=TODAY, backfill_days=20)

    assert run.status == "ok"
    assert run.rows_upserted == (21 + 21)  # GSC ends today-3 and GA4 ends today; 20 days back is 21 days inclusive
    assert run.detail[project.slug]["status"] == "ok"
    assert await _count_days(project.id) == 21 + 3  # GA4 covers 3 more (most recent) days than GSC

    (snapshot,) = await _snapshots(project.id)
    assert snapshot.configured is True
    assert snapshot.clicks == {"recent": 70, "prior": 70, "pct_change": 0.0}
    assert snapshot.sessions["recent"] == 56
    assert snapshot.alert_severity == "green"
    assert snapshot.alert_messages == []


async def test_one_failing_project_does_not_stop_the_other():
    good = await _project(gsc="sc-domain:good.example")
    broken = await _project(gsc="sc-domain:broken.example")

    run = await run_once(http_session=google_fake(failing="broken.example"), today=TODAY, backfill_days=20)

    assert run.status == "partial"
    assert run.detail[good.slug]["status"] == "ok"
    assert run.detail[broken.slug]["status"] == "error"
    assert "403" in run.detail[broken.slug]["errors"][0]
    assert await _count_days(good.id) > 0

    (broken_snapshot,) = await _snapshots(broken.id)
    assert broken_snapshot.alert_severity == "yellow"
    assert broken_snapshot.alert_messages[0]["message"].startswith("Traffic pull failed: GSC:")
    (good_snapshot,) = await _snapshots(good.id)
    assert good_snapshot.alert_severity == "green"


async def test_all_projects_failing_is_an_error_run():
    await _project(gsc="sc-domain:broken-a.example")
    await _project(ga4="properties/broken-b")

    run = await run_once(http_session=google_fake(failing="broken"), today=TODAY, backfill_days=20)
    assert run.status == "error"


async def test_failed_pull_keeps_showing_the_last_known_trend():
    project = await _project(gsc="sc-domain:flaky.example")
    await run_once(http_session=google_fake(), today=TODAY, backfill_days=20)

    await run_once(http_session=google_fake(failing="flaky.example"), today=TODAY)

    latest = (await _snapshots(project.id))[0]
    assert latest.alert_severity == "yellow"
    assert latest.clicks["recent"] == 70


async def test_one_source_failing_keeps_the_other_sources_rows():
    project = await _project(gsc="sc-domain:half.example", ga4="properties/half")

    run = await run_once(http_session=google_fake(failing="properties/half"), today=TODAY, backfill_days=20)

    assert run.status == "error"
    assert run.detail[project.slug]["errors"][0].startswith("GA4:")
    assert await _count_days(project.id) == 21  # the GSC rows survived
    (snapshot,) = await _snapshots(project.id)
    assert snapshot.clicks is not None and snapshot.sessions is None


async def test_no_credentials_is_skipped():
    await _project(gsc="sc-domain:unused.example")
    run = await run_once(http_session=None, today=TODAY)
    assert run.status == "skipped"
    assert run.rows_upserted == 0
    assert run.detail == {"reason": "no credentials"}


async def test_no_configured_projects_is_skipped():
    session = google_fake()
    run = await run_once(http_session=session, today=TODAY)
    assert run.status == "skipped"
    assert run.detail == {"reason": "no configured projects"}
    assert session.calls == []


async def test_demo_projects_are_never_collected():
    await _project(gsc="sc-domain:demo.example", is_demo=True)
    session = google_fake()
    run = await run_once(http_session=session, today=TODAY)
    assert run.status == "skipped"
    assert session.calls == []


def _gsc_window(session: FakeSession) -> tuple[date, date]:
    body = next(c["json"] for c in session.calls if "searchconsole" in c["url"])
    return date.fromisoformat(body["startDate"]), date.fromisoformat(body["endDate"])


async def test_new_project_uses_the_backfill_window_then_the_short_refresh_window():
    project = await _project(gsc="sc-domain:window.example")

    first = google_fake()
    await run_once(http_session=first, today=TODAY)
    start, end = _gsc_window(first)
    assert end == TODAY - timedelta(days=3)  # Search Console data is provisional for ~3 days
    assert (end - start).days == settings.collect_backfill_days
    assert await _count_days(project.id) == settings.collect_backfill_days + 1

    second = google_fake()
    await run_once(http_session=second, today=TODAY)
    start, end = _gsc_window(second)
    assert (end - start).days == 35


async def test_explicit_backfill_days_overrides_both():
    await _project(gsc="sc-domain:override.example")
    session = google_fake()
    await run_once(http_session=session, today=TODAY, backfill_days=10)
    start, end = _gsc_window(session)
    assert (end - start).days == 10


async def test_ga4_window_ends_today():
    await _project(ga4="properties/ends-today")
    session = google_fake()
    await run_once(http_session=session, today=TODAY, backfill_days=5)
    body = session.calls[0]["json"]
    assert body["dateRanges"][0]["endDate"] == TODAY.isoformat()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["dateRanges"][0]["startDate"])
