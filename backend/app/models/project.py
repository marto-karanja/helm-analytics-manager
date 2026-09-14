import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Project(Base):
    """Unifies portfolio_manager entries and seo_dashboard pipeline entries.

    A pipeline project additionally has PipelineSnapshot/TrafficSnapshot rows.
    """

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # stable external identity for sync upserts (markdown filename stem, or
    # seo_dashboard task_name) -- distinct from `name`, which is freeform and
    # user-editable via the UI.
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    local_repo: Mapped[str | None] = mapped_column(Text, nullable=True)
    operational_signals: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)

    # editable fields, seeded from portfolio_manager markdown on first import
    goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    blockers: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_pipeline: Mapped[bool] = mapped_column(Boolean, default=False)
    # demo projects are a separate, frozen dataset shown only to the demo
    # account -- never live-synced, never mixed with the real user's rows.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    pipeline_task_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gsc_site_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ga4_property_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    pipeline_snapshots: Mapped[list["PipelineSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="PipelineSnapshot.synced_at.desc()"
    )
    traffic_snapshots: Mapped[list["TrafficSnapshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="TrafficSnapshot.synced_at.desc()"
    )


class PipelineSnapshot(Base):
    """One row per sync_to_hub.py run, from seo_dashboard.metrics.compute_metrics()."""

    __tablename__ = "pipeline_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    total_articles_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backlog_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blocked_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oldest_backlog_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_7_runs: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # merged output of alerts.evaluate() + search_alerts.evaluate_search()
    alert_severity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alert_messages: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="pipeline_snapshots")


class TrafficSnapshot(Base):
    """One row per sync_to_hub.py run, from seo_dashboard.search_metrics.compute_search_metrics()."""

    __tablename__ = "traffic_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    configured: Mapped[bool] = mapped_column(Boolean, default=False)
    clicks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    impressions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sessions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # from search_alerts.evaluate_search()
    alert_severity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alert_messages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="traffic_snapshots")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo | in_progress | done
    priority: Mapped[str] = mapped_column(String(20), default="normal")  # low | normal | high
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")
