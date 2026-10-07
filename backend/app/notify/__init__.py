"""Notification channels behind one interface, so alert logic never knows which channels exist."""
import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.core.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

EMOJI = {"opened": "\U0001F6A8", "escalated": "\U0001F525", "recovered": "✅"}


@dataclass(frozen=True)
class Notification:
    transition: str  # opened | escalated | recovered
    project_slug: str
    alert_kind: str
    severity: str
    message: str

    @property
    def subject(self) -> str:
        label = {"opened": self.severity.upper(), "escalated": "ESCALATED", "recovered": "RECOVERED"}[self.transition]
        return f"[Helm] {label}: {self.project_slug} - {self.message}"

    @property
    def body(self) -> str:
        return f"{self.project_slug}: {self.message}\nKind: {self.alert_kind}\nSeverity: {self.severity}\nChange: {self.transition}\n"


class Notifier(Protocol):
    name: str

    async def send(self, notification: Notification) -> None: ...


class EmailNotifier:
    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, recipients: list[str]):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.recipients = sender, recipients

    def _send_sync(self, notification: Notification) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = notification.subject, self.sender, ", ".join(self.recipients)
        msg.set_content(notification.body)
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)

    async def send(self, notification: Notification) -> None:
        await asyncio.to_thread(self._send_sync, notification)


class TelegramNotifier:
    name = "telegram"

    def __init__(self, token: str, chat_id: str, client_factory=httpx.AsyncClient):
        self.token, self.chat_id, self._client_factory = token, chat_id, client_factory

    async def send(self, notification: Notification) -> None:
        text = f"{EMOJI[notification.transition]} {notification.subject}"
        async with self._client_factory(timeout=15) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage", json={"chat_id": self.chat_id, "text": text}
            )
            response.raise_for_status()


def recipients_of(settings: Settings) -> list[str]:
    return [a.strip() for a in settings.report_recipients.split(",") if a.strip()]


def build_notifiers(settings: Settings = default_settings) -> list[Notifier]:
    notifiers: list[Notifier] = []
    recipients = recipients_of(settings)
    if settings.smtp_host and settings.smtp_from and recipients:
        notifiers.append(
            EmailNotifier(settings.smtp_host, settings.smtp_port, settings.smtp_user, settings.smtp_password, settings.smtp_from, recipients)
        )
    if settings.telegram_bot_token and settings.telegram_chat_id:
        notifiers.append(TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id))
    return notifiers


async def notify(notifiers: list[Notifier], notification: Notification) -> int:
    """Sends through every channel; one failing channel never blocks the others. Returns how many succeeded.

    Only ids and counts are logged: never the message body or credentials."""
    sent = 0
    for notifier in notifiers:
        try:
            await notifier.send(notification)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("notification via %s failed for %s/%s: %s", notifier.name, notification.project_slug, notification.alert_kind, type(exc).__name__)
    return sent
