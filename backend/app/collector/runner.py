import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collector import alerts as alert_rules
from app.collector.ga4 import fetch_ga4_daily
from app.collector.gsc import fetch_gsc_daily
from app.collector.store import upsert_traffic_daily
from app.collector.summary import GSC_LAG_DAYS, WINDOW_DAYS, compute_summary
from app.core.config import settings
from app.db.session import async_session_maker
from app.models.project import CollectorRun, Project, TrafficDaily, TrafficSnapshot

logger = logging.getLogger("helm.collector")

REFRESH_DAYS = 35  # re-pull a month so provisional Search Console days get their final values
MAX_STORED_ERROR_CHARS = 300


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_STORED_ERROR_CHARS]


async def _load_summary(db: AsyncSession, project_id, today: date) -> dict:
    earliest = today - timedelta(days=GSC_LAG_DAYS + 2 * WINDOW_DAYS)
    result = await db.execute(
        select(TrafficDaily).where(TrafficDaily.project_id == project_id, TrafficDaily.metric_date >= earliest)
    )
    rows = [
        {
            "metric_date": r.metric_date,
            "clicks": r.clicks,
            "impressions": r.impressions,
            "avg_position": r.avg_position,
            "sessions": r.sessions,
        }
        for r in result.scalars()
    ]
    return compute_summary(rows, today)


async def _collect_project(
    db: AsyncSession, project: Project, http_session, today: date, backfill_days: int | None
) -> dict:
    """Pulls each configured source; a failing source is recorded but does not lose the other's rows."""
    has_rows = (
        await db.execute(select(TrafficDaily.id).where(TrafficDaily.project_id == project.id).limit(1))
    ).first() is not None
    if backfill_days is not None:
        days = backfill_days
    else:
        days = REFRESH_DAYS if has_rows else settings.collect_backfill_days

    rows_upserted = 0
    errors: list[str] = []

    if project.gsc_site_url:
        # GSC data is only final ~3 days back, so never ask for anything newer.
        end = today - timedelta(days=GSC_LAG_DAYS)
        try:
            rows = await asyncio.to_thread(fetch_gsc_daily, http_session, project.gsc_site_url, end - timedelta(days=days), end)
            rows_upserted += await upsert_traffic_daily(db, project.id, rows)
        except Exception as exc:  # noqa: BLE001 -- one failing source must not stop the run
            await db.rollback()
            logger.warning("GSC pull failed for %s: %s", project.slug, _error_text(exc))
            errors.append(f"GSC: {_error_text(exc)}")

    if project.ga4_property_id:
        try:
            rows = await asyncio.to_thread(fetch_ga4_daily, http_session, project.ga4_property_id, today - timedelta(days=days), today)
            rows_upserted += await upsert_traffic_daily(db, project.id, rows)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.warning("GA4 pull failed for %s: %s", project.slug, _error_text(exc))
            errors.append(f"GA4: {_error_text(exc)}")

    # Summarised from stored rows even after a failure, so the UI keeps showing the last known trend
    # next to the "pull failed" alert instead of going blank.
    summary = await _load_summary(db, project.id, today)
    alerts = alert_rules.evaluate(summary) + [alert_rules.pull_failed_alert(e) for e in errors]
    db.add(
        TrafficSnapshot(
            project_id=project.id,
            configured=True,
            clicks=summary["clicks"],
            impressions=summary["impressions"],
            sessions=summary["sessions"],
            alert_severity=alert_rules.overall_severity(alerts),
            alert_messages=alerts,
        )
    )
    await db.commit()
    return {"status": "error" if errors else "ok", "rows": rows_upserted, "days": days, "errors": errors}


async def _record_run(
    session_factory: Callable, started_at: datetime, status: str, detail: dict, rows: int, kind: str = "traffic"
) -> CollectorRun:
    run = CollectorRun(
        kind=kind,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        status=status,
        detail=detail,
        rows_upserted=rows,
    )
    async with session_factory() as db:
        db.add(run)
        await db.commit()
    return run


async def run_once(
    session_factory: Callable = async_session_maker,
    http_session=None,
    today: date | None = None,
    backfill_days: int | None = None,
) -> CollectorRun:
    """One collection pass. `http_session=None` means no credentials: nothing is pulled and the run is `skipped`."""
    started_at = datetime.now(timezone.utc)
    today = today or date.today()

    if http_session is None:
        logger.info("No Google credentials configured; collector is idle (skipped)")
        return await _record_run(session_factory, started_at, "skipped", {"reason": "no credentials"}, 0)

    async with session_factory() as db:
        result = await db.execute(
            select(Project)
            .where(Project.is_demo.is_(False), or_(Project.gsc_site_url.is_not(None), Project.ga4_property_id.is_not(None)))
            .order_by(Project.slug)
        )
        projects = [p for p in result.scalars() if p.gsc_site_url or p.ga4_property_id]

    if not projects:
        logger.info("No projects have gsc_site_url or ga4_property_id set; nothing to collect (skipped)")
        return await _record_run(session_factory, started_at, "skipped", {"reason": "no configured projects"}, 0)

    detail: dict[str, dict] = {}
    for project in projects:
        try:
            async with session_factory() as db:
                detail[project.slug] = await _collect_project(db, project, http_session, today, backfill_days)
        except Exception as exc:  # noqa: BLE001 -- e.g. the database failing for this one project
            logger.exception("Collection failed for %s", project.slug)
            detail[project.slug] = {"status": "error", "rows": 0, "errors": [_error_text(exc)]}

    failed = [d for d in detail.values() if d["status"] == "error"]
    status = "ok" if not failed else "error" if len(failed) == len(detail) else "partial"
    rows = sum(d["rows"] for d in detail.values())
    logger.info("Collector run %s: %d project(s), %d row(s) upserted", status, len(detail), rows)
    return await _record_run(session_factory, started_at, status, detail, rows)
