import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    category: str
    url: str
    local_repo: str | None
    operational_signals: str | None
    last_updated: date | None
    goals: str | None
    current_status: str | None
    blockers: str | None
    priority_notes: str | None
    is_pipeline: bool
    pipeline_task_name: str | None
    gsc_site_url: str | None
    ga4_property_id: str | None
    created_at: datetime
    updated_at: datetime
    latest_alert_severity: str | None = None
    open_task_count: int = 0


class ProjectUpdate(BaseModel):
    goals: str | None = None
    current_status: str | None = None
    blockers: str | None = None
    priority_notes: str | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime


class TaskWithProjectRead(TaskRead):
    project_name: str
    project_slug: str


class TaskCreate(BaseModel):
    title: str
    status: str = "todo"
    priority: str = "normal"


class TaskUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    priority: str | None = None


class PipelineSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    synced_at: datetime
    total_articles_written: int | None
    backlog_count: int | None
    blocked_count: int | None
    oldest_backlog_age_days: int | None
    last_published_at: datetime | None
    last_7_runs: list | None
    alert_severity: str | None
    alert_messages: list | None


class TrafficSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    synced_at: datetime
    configured: bool
    clicks: dict | None
    impressions: dict | None
    sessions: dict | None
    alert_severity: str | None
    alert_messages: list | None


class ProjectDetailRead(ProjectRead):
    tasks: list[TaskRead]
    pipeline_snapshots: list[PipelineSnapshotRead]
    traffic_snapshots: list[TrafficSnapshotRead]
