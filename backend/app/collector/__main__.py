import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.collector.google import build_session
from app.collector.runner import MAX_STORED_ERROR_CHARS, _record_run, run_once
from app.core.config import settings
from app.db.session import async_session_maker
from app.indexing import jobs as indexing_jobs
from app.keywords.rollup import run_gsc_query_rollup
from app.models.project import CollectorRun

logger = logging.getLogger("helm.collector")

DAILY = timedelta(hours=24)
WEEKLY = timedelta(days=7)

# Two missed runs of a job; anything longer means the loop is stuck or dead.
HEALTHY_MAX_AGE = {
    "traffic": timedelta(hours=36),
    "sitemap_walk": timedelta(hours=36),
    "page_signals": timedelta(hours=36),
    "url_inspection": timedelta(hours=36),
    "gsc_query_rollup": timedelta(days=8),
}
# A job that last failed or was skipped is retried after this, not after its full interval.
RETRY_AFTER = timedelta(hours=1)


def intervals() -> dict[str, timedelta]:
    return {
        "traffic": timedelta(hours=settings.collect_interval_hours),
        "sitemap_walk": DAILY,
        "page_signals": DAILY,
        "url_inspection": DAILY,
        "gsc_query_rollup": WEEKLY,
    }


async def is_healthy(session_factory: Callable = async_session_maker, now: datetime | None = None) -> bool:
    path = settings.google_credentials_file
    if not path or not os.path.isfile(path):
        return True  # an install without analytics is not unhealthy
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        newest = dict(
            (await db.execute(select(CollectorRun.kind, func.max(CollectorRun.finished_at)).group_by(CollectorRun.kind))).all()
        )
    # Traffic is mandatory. The other kinds are checked once they have run at all, so a job that died after
    # its first run goes unhealthy, and a weekly job's quiet days do not trip the daily limit.
    if newest.get("traffic") is None or now - newest["traffic"] >= HEALTHY_MAX_AGE["traffic"]:
        return False
    return all(now - finished < HEALTHY_MAX_AGE[kind] for kind, finished in newest.items() if kind in HEALTHY_MAX_AGE)


async def is_due(kind: str, session_factory: Callable = async_session_maker, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        last = (
            await db.execute(
                select(CollectorRun.finished_at, CollectorRun.status)
                .where(CollectorRun.kind == kind)
                .order_by(CollectorRun.finished_at.desc())
                .limit(1)
            )
        ).first()
    if last is None:
        return True
    finished_at, status = last
    wait = RETRY_AFTER if status in {"error", "skipped"} else intervals()[kind]
    return now - finished_at >= min(wait, intervals()[kind])


async def _run_job(kind: str, work: Callable[[], Awaitable[dict]]) -> None:
    """Runs one indexing/keyword job and records its collector_runs row, whatever happens."""
    started_at = datetime.now(timezone.utc)
    try:
        outcome = await work()
        await _record_run(async_session_maker, started_at, outcome["status"], outcome["detail"], outcome["rows"], kind=kind)
    except Exception as exc:  # noqa: BLE001 -- one failing job must not stop the others
        logger.exception("Job %s failed", kind)
        try:
            error = {"error": f"{type(exc).__name__}: {exc}"[:MAX_STORED_ERROR_CHARS]}
            await _record_run(async_session_maker, started_at, "error", error, 0, kind=kind)
        except Exception:  # noqa: BLE001 -- e.g. the database is down
            logger.exception("Could not record the failed %s run either", kind)


async def _skipped(reason: str) -> dict:
    return {"status": "skipped", "detail": {"reason": reason}, "rows": 0}


async def run_pass(backfill_days: int | None, force: bool, only: str | None = None) -> None:
    """One scheduler tick: every job that is due (or all of them when forced) runs once."""

    def wanted(kind: str) -> bool:
        return only in (None, kind)

    google_session = None
    try:
        google_session = build_session(settings.google_credentials_file)
    except Exception:  # noqa: BLE001 -- a malformed key file is recorded by the traffic job below
        logger.exception("Could not build the Google session")

    if wanted("traffic") and (force or await is_due("traffic")):
        started_at = datetime.now(timezone.utc)
        try:
            await run_once(http_session=google_session, backfill_days=backfill_days)
        except Exception as exc:  # noqa: BLE001 -- one bad iteration must not kill the container
            logger.exception("Collector iteration failed")
            try:
                await _record_run(
                    async_session_maker, started_at, "error", {"error": f"{type(exc).__name__}: {exc}"[:MAX_STORED_ERROR_CHARS]}, 0
                )
            except Exception:  # noqa: BLE001 -- e.g. the database is not migrated yet
                logger.exception("Could not record the failed run either")

    async def sitemap_walk() -> dict:
        return await indexing_jobs.run_sitemap_walk(async_session_maker, google_session)

    async def page_signals() -> dict:
        return await indexing_jobs.run_page_signals(async_session_maker)

    async def url_inspection() -> dict:
        if google_session is None:
            return await _skipped("no credentials")
        return await indexing_jobs.run_url_inspection(async_session_maker, google_session)

    async def query_rollup() -> dict:
        if google_session is None:
            return await _skipped("no credentials")
        return await run_gsc_query_rollup(async_session_maker, google_session)

    if google_session is not None and only is None:
        try:  # every tick, not on an interval: "Inspect now" should not wait a day
            await indexing_jobs.run_inspect_requests(async_session_maker, google_session)
        except Exception:  # noqa: BLE001
            logger.exception("Processing manual inspection requests failed")

    # Order matters on a first run: the URL list feeds signals, and signals feed inspection priority.
    for kind, work in (
        ("sitemap_walk", sitemap_walk),
        ("page_signals", page_signals),
        ("url_inspection", url_inspection),
        ("gsc_query_rollup", query_rollup),
    ):
        if wanted(kind) and (force or await is_due(kind)):
            await _run_job(kind, work)


async def loop(backfill_days: int | None, once: bool, only: str | None = None) -> None:
    while True:
        try:
            await run_pass(backfill_days, force=once, only=only)
        except Exception:  # noqa: BLE001 -- e.g. the due-check query failing while the database is down
            logger.exception("Scheduler pass failed")
        if once:
            return
        await asyncio.sleep(settings.scheduler_tick_seconds)
        backfill_days = None  # an override only applies to the first pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.collector")
    parser.add_argument("--once", action="store_true", help="run every job once, due or not, and exit")
    parser.add_argument("--job", choices=sorted(HEALTHY_MAX_AGE), help="restrict to one job kind")
    parser.add_argument("--backfill-days", type=int, help="override the traffic pull window (days back)")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 if healthy, 1 otherwise")
    args = parser.parse_args(argv)

    if args.healthcheck:
        return 0 if asyncio.run(is_healthy()) else 1

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(loop(args.backfill_days, args.once, args.job))
    return 0


if __name__ == "__main__":
    sys.exit(main())
