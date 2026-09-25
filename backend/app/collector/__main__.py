import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.collector.google import build_session
from app.collector.runner import MAX_STORED_ERROR_CHARS, _record_run, run_once
from app.core.config import settings
from app.db.session import async_session_maker
from app.models.project import CollectorRun

logger = logging.getLogger("helm.collector")

# Two missed daily runs; anything longer means the loop is stuck or dead.
HEALTHY_MAX_AGE = timedelta(hours=36)
# While idle without credentials, look again soon so dropping the key file in does not wait a full interval.
IDLE_RECHECK = timedelta(hours=1)


async def is_healthy(session_factory: Callable = async_session_maker, now: datetime | None = None) -> bool:
    path = settings.google_credentials_file
    if not path or not os.path.isfile(path):
        return True  # an install without analytics is not unhealthy
    now = now or datetime.now(timezone.utc)
    async with session_factory() as db:
        newest = (await db.execute(select(func.max(CollectorRun.finished_at)))).scalar_one()
    return newest is not None and now - newest < HEALTHY_MAX_AGE


async def loop(backfill_days: int | None, once: bool) -> None:
    while True:
        started_at = datetime.now(timezone.utc)
        sleep_for = timedelta(hours=settings.collect_interval_hours)
        try:
            http_session = build_session(settings.google_credentials_file)
            run = await run_once(http_session=http_session, backfill_days=backfill_days)
            if run.status == "skipped":
                sleep_for = min(sleep_for, IDLE_RECHECK)
        except Exception as exc:  # noqa: BLE001 -- one bad iteration must not kill the container
            logger.exception("Collector iteration failed")
            try:
                await _record_run(
                    async_session_maker, started_at, "error", {"error": f"{type(exc).__name__}: {exc}"[:MAX_STORED_ERROR_CHARS]}, 0
                )
            except Exception:  # noqa: BLE001 -- e.g. the database is down or not migrated yet
                logger.exception("Could not record the failed run either")
        if once:
            return
        await asyncio.sleep(sleep_for.total_seconds())
        backfill_days = None  # an override only applies to the first pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.collector")
    parser.add_argument("--once", action="store_true", help="run a single pass and exit")
    parser.add_argument("--backfill-days", type=int, help="override the pull window (days back)")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 if healthy, 1 otherwise")
    args = parser.parse_args(argv)

    if args.healthcheck:
        return 0 if asyncio.run(is_healthy()) else 1

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(loop(args.backfill_days, args.once))
    return 0


if __name__ == "__main__":
    sys.exit(main())
