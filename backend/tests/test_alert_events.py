import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.alerts.events import apply_alerts
from app.db.session import async_session_maker
from app.models.alerts import AlertEvent
from app.models.project import Project
from app.notify import EmailNotifier, Notification, TelegramNotifier, build_notifiers, notify

T0 = datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)


class FakeNotifier:
    name = "fake"

    def __init__(self, fail=False):
        self.sent: list[Notification] = []
        self.fail = fail

    async def send(self, notification):
        if self.fail:
            raise RuntimeError("smtp down with secret-password")
        self.sent.append(notification)


def red(kind="zero_impressions", msg="Zero impressions"):
    return {"kind": kind, "severity": "red", "message": msg}


def yellow(kind="no_data", msg="No data"):
    return {"kind": kind, "severity": "yellow", "message": msg}


async def make_project() -> Project:
    async with async_session_maker() as db:
        p = Project(slug=f"al-{uuid.uuid4().hex[:8]}", name="al", category="seo-content-site", url="https://a.example/")
        db.add(p)
        await db.commit()
        return p


async def run(project, alerts, notifier, at, **kw):
    async with async_session_maker() as db:
        return await apply_alerts(db, project, alerts, [notifier], now=at, **kw)


async def events(project):
    async with async_session_maker() as db:
        return list(
            (await db.execute(select(AlertEvent).where(AlertEvent.project_id == project.id).order_by(AlertEvent.opened_at))).scalars()
        )


async def test_transition_into_red_opens_and_notifies():
    p, n = await make_project(), FakeNotifier()
    sent = await run(p, [red()], n, T0)
    assert [s.transition for s in sent] == ["opened"]
    (e,) = await events(p)
    assert e.state == "open" and e.severity == "red" and e.last_notified_at == T0


async def test_staying_red_sends_nothing_new():
    p, n = await make_project(), FakeNotifier()
    await run(p, [red()], n, T0)
    for day in (1, 2, 3):
        assert await run(p, [red(msg="still zero")], n, T0 + timedelta(days=day)) == []
    assert len(n.sent) == 1
    (e,) = await events(p)
    assert e.state == "open" and e.message == "still zero"


async def test_transition_out_resolves_and_notifies_recovered():
    p, n = await make_project(), FakeNotifier()
    await run(p, [red()], n, T0)
    sent = await run(p, [], n, T0 + timedelta(days=1))
    assert [s.transition for s in sent] == ["recovered"]
    (e,) = await events(p)
    assert e.state == "resolved" and e.resolved_at == T0 + timedelta(days=1)
    assert await run(p, [], n, T0 + timedelta(days=2)) == []  # and then silence


async def test_yellow_to_red_escalates_but_red_to_yellow_is_quiet():
    p, n = await make_project(), FakeNotifier()
    await run(p, [yellow("clicks_drop")], n, T0)
    sent = await run(p, [red("clicks_drop")], n, T0 + timedelta(days=1), min_interval=timedelta(0))
    assert [s.transition for s in sent] == ["escalated"]
    assert await run(p, [yellow("clicks_drop")], n, T0 + timedelta(days=2)) == []
    (e,) = await events(p)
    assert e.severity == "yellow"


async def test_kinds_are_independent():
    p, n = await make_project(), FakeNotifier()
    await run(p, [red(), yellow()], n, T0)
    sent = await run(p, [yellow()], n, T0 + timedelta(days=1))
    assert [(s.alert_kind, s.transition) for s in sent] == [("zero_impressions", "recovered")]


async def test_failed_pull_never_resolves_open_events():
    p, n = await make_project(), FakeNotifier()
    await run(p, [red()], n, T0)
    pull = {"kind": "pull_failed", "severity": "yellow", "message": "Traffic pull failed"}
    sent = await run(p, [pull], n, T0 + timedelta(days=1))
    assert [s.alert_kind for s in sent] == ["pull_failed"]
    open_kinds = {e.kind for e in await events(p) if e.state == "open"}
    assert open_kinds == {"zero_impressions", "pull_failed"}


async def test_rate_limit_suppresses_a_flap_inside_the_window_but_not_recovery():
    p, n = await make_project(), FakeNotifier()
    await run(p, [red()], n, T0)
    rec = await run(p, [], n, T0 + timedelta(hours=1))
    assert [s.transition for s in rec] == ["recovered"]  # recovery is never suppressed
    again = await run(p, [red()], n, T0 + timedelta(hours=2))
    assert again == []  # re-open inside 6h of the last notice is dropped
    assert len(await events(p)) == 2  # ...but still recorded
    later = await run(p, [], n, T0 + timedelta(hours=3))
    assert [s.transition for s in later] == ["recovered"]
    fresh = await run(p, [red()], n, T0 + timedelta(hours=10))
    assert [s.transition for s in fresh] == ["opened"]


async def test_failing_channel_does_not_block_state_or_other_channels():
    p = await make_project()
    bad, good = FakeNotifier(fail=True), FakeNotifier()
    async with async_session_maker() as db:
        sent = await apply_alerts(db, p, [red()], [bad, good], now=T0)
    assert len(sent) == 1 and len(good.sent) == 1
    (e,) = await events(p)
    assert e.state == "open"


async def test_no_working_channel_leaves_last_notified_unset():
    p = await make_project()
    async with async_session_maker() as db:
        assert await apply_alerts(db, p, [red()], [FakeNotifier(fail=True)], now=T0) == []
    (e,) = await events(p)
    assert e.last_notified_at is None


async def test_notify_logs_no_secrets(caplog):
    with caplog.at_level("WARNING"):
        await notify([FakeNotifier(fail=True)], Notification("opened", "x", "k", "red", "m"))
    assert "secret-password" not in caplog.text and "RuntimeError" in caplog.text


async def test_telegram_posts_to_bot_api():
    calls = []

    class Client:
        def __init__(self, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, url, json):
            calls.append((url, json))
            class R:
                def raise_for_status(self): ...
            return R()

    await TelegramNotifier("TOKEN", "42", client_factory=Client).send(Notification("opened", "site", "k", "red", "Zero"))
    assert calls[0][0] == "https://api.telegram.org/botTOKEN/sendMessage" and calls[0][1]["chat_id"] == "42"
    assert "site" in calls[0][1]["text"]


def test_email_sends_only_to_configured_recipients(monkeypatch):
    sent = []

    class SMTP:
        def __init__(self, host, port, timeout): ...
        def __enter__(self): return self
        def __exit__(self, *a): ...
        def starttls(self): ...
        def login(self, u, p): ...
        def send_message(self, msg): sent.append(msg)

    monkeypatch.setattr("app.notify.smtplib.SMTP", SMTP)
    EmailNotifier("h", 587, "u", "p", "helm@x.example", ["a@x.example", "b@x.example"])._send_sync(
        Notification("recovered", "site", "k", "red", "Recovered: Zero")
    )
    assert sent[0]["To"] == "a@x.example, b@x.example" and sent[0]["Subject"].startswith("[Helm] RECOVERED")


def test_build_notifiers_needs_complete_config():
    from app.core.config import settings

    cfg = settings.model_copy(update={"smtp_host": "h", "smtp_from": "", "report_recipients": "", "telegram_bot_token": "", "telegram_chat_id": ""})
    assert build_notifiers(cfg) == []
    cfg = cfg.model_copy(update={"smtp_from": "f@x.example", "report_recipients": "a@x.example, ", "telegram_bot_token": "t", "telegram_chat_id": "1"})
    assert [n.name for n in build_notifiers(cfg)] == ["email", "telegram"]
