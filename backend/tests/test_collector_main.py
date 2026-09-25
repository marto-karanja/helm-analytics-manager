import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete

from app.collector import __main__ as collector_main
from app.collector.google import build_session
from app.collector.runner import _record_run
from app.core.config import settings
from app.db.session import async_session_maker
from app.models.project import CollectorRun


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    path = tmp_path / "google-sa.json"
    path.write_text("{}")  # only its existence matters to the healthcheck; the content is never read
    monkeypatch.setattr(settings, "google_credentials_file", str(path))
    return path


async def _clear_runs() -> None:
    async with async_session_maker() as session:
        await session.execute(delete(CollectorRun))
        await session.commit()


def test_build_session_is_none_without_a_key(tmp_path):
    assert build_session("") is None
    assert build_session(str(tmp_path / "missing.json")) is None


async def test_healthy_when_no_credentials_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_credentials_file", "")
    assert await collector_main.is_healthy() is True


async def test_healthy_when_credentials_path_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "google_credentials_file", str(tmp_path / "absent.json"))
    assert await collector_main.is_healthy() is True


async def test_unhealthy_with_credentials_and_no_runs(key_file):
    await _clear_runs()
    assert await collector_main.is_healthy() is False


async def test_healthy_with_a_recent_run_and_unhealthy_with_a_stale_one(key_file):
    await _clear_runs()
    await _record_run(async_session_maker, datetime.now(timezone.utc), "error", {}, 0)  # any finished run is liveness
    assert await collector_main.is_healthy() is True

    future = datetime.now(timezone.utc) + timedelta(hours=37)
    assert await collector_main.is_healthy(now=future) is False


async def test_healthcheck_flag_exit_codes(monkeypatch):
    async def healthy() -> bool:
        return True

    async def unhealthy() -> bool:
        return False

    monkeypatch.setattr(collector_main, "is_healthy", healthy)
    # main() owns its event loop, so it runs in a thread while the test loop is running
    assert await asyncio.to_thread(collector_main.main, ["--healthcheck"]) == 0
    monkeypatch.setattr(collector_main, "is_healthy", unhealthy)
    assert await asyncio.to_thread(collector_main.main, ["--healthcheck"]) == 1


async def test_loop_once_records_a_skipped_run_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "google_credentials_file", "")
    await _clear_runs()
    await collector_main.loop(backfill_days=None, once=True)
    async with async_session_maker() as session:
        runs = (await session.execute(CollectorRun.__table__.select())).all()
    assert [r.status for r in runs] == ["skipped"]


async def test_loop_survives_and_records_an_unexpected_exception(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(collector_main, "run_once", boom)
    await _clear_runs()
    await collector_main.loop(backfill_days=None, once=True)  # must not raise
    async with async_session_maker() as session:
        (run,) = (await session.execute(CollectorRun.__table__.select())).all()
    assert run.status == "error"
    assert "kaboom" in run.detail["error"]


async def test_loop_keeps_going_after_a_failed_iteration(monkeypatch):
    calls = []

    async def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first pass fails")
        raise SystemExit  # stop the otherwise endless loop on the second pass

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(collector_main, "run_once", flaky)
    monkeypatch.setattr(collector_main.asyncio, "sleep", no_sleep)
    with pytest.raises(SystemExit):
        await collector_main.loop(backfill_days=None, once=False)
    assert len(calls) == 2
