"""Alert state machine: turns each run's current alerts into open/resolved events and notifications.

Per (project, kind):
  nothing open + active          -> open an event, notify "opened"
  open, severity rose            -> update, notify "escalated"
  open, same or lower severity   -> update quietly (no repeat notification)
  open, no longer active         -> resolve, notify "recovered"
A run whose traffic pull failed never resolves anything: stale data says nothing about recovery.
A notification for a (project, kind) is skipped if one went out within `min_interval`; recovered notices are
never suppressed. Suppressed notices are dropped (the event itself is still recorded and visible).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import AlertEvent
from app.models.project import Project
from app.notify import Notification, Notifier, notify

logger = logging.getLogger(__name__)

_RANK = {"yellow": 1, "red": 2}


async def apply_alerts(
    db: AsyncSession,
    project: Project,
    alerts: list[dict],
    notifiers: list[Notifier],
    now: datetime | None = None,
    min_interval: timedelta = timedelta(hours=6),
) -> list[Notification]:
    now = now or datetime.now(timezone.utc)
    pull_failed = any(a["kind"] == "pull_failed" for a in alerts)
    active = {a["kind"]: a for a in alerts if a["severity"] in _RANK}

    open_events = {
        e.kind: e
        for e in (
            await db.execute(select(AlertEvent).where(AlertEvent.project_id == project.id, AlertEvent.state == "open"))
        ).scalars()
    }

    pending: list[tuple[AlertEvent, Notification]] = []
    for kind, alert in active.items():
        event = open_events.get(kind)
        if event is None:
            event = AlertEvent(
                project_id=project.id, kind=kind, severity=alert["severity"], state="open", opened_at=now, message=alert["message"], details=alert.get("details")
            )
            # Inherit the last notification time so a flap (red, recovered, red) can't beat the rate limit.
            event.last_notified_at = (
                await db.execute(
                    select(func.max(AlertEvent.last_notified_at)).where(AlertEvent.project_id == project.id, AlertEvent.kind == kind)
                )
            ).scalar()
            db.add(event)
            pending.append((event, Notification("opened", project.slug, kind, alert["severity"], alert["message"])))
            continue
        rose = _RANK[alert["severity"]] > _RANK[event.severity]
        event.severity, event.message = alert["severity"], alert["message"]
        if rose:
            pending.append((event, Notification("escalated", project.slug, kind, alert["severity"], alert["message"])))

    if not pull_failed:
        for kind, event in open_events.items():
            if kind not in active:
                event.state, event.resolved_at = "resolved", now
                pending.append((event, Notification("recovered", project.slug, kind, event.severity, f"Recovered: {event.message}")))

    sent: list[Notification] = []
    for event, notification in pending:
        recently = event.last_notified_at is not None and now - event.last_notified_at < min_interval
        if notification.transition != "recovered" and recently:
            continue
        if await notify(notifiers, notification):
            event.last_notified_at = now
            sent.append(notification)
    await db.commit()
    return sent
