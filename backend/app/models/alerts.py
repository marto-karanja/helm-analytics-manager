import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AlertEvent(Base):
    """One open/resolved episode of an alert kind on a project. The notification source; the per-run
    `traffic_snapshots.alert_messages` stay as the UI's view of the latest state."""

    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_project_kind_state", "project_id", "kind", "state"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))  # yellow | red
    state: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
