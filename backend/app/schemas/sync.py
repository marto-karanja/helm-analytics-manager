from pydantic import BaseModel


class PortfolioSyncItem(BaseModel):
    slug: str
    name: str
    category: str
    url: str
    local_repo: str | None = None
    operational_signals: str | None = None
    last_updated: str | None = None
    goals: str | None = None
    current_status: str | None = None
    blockers: str | None = None
    priority_notes: str | None = None


class PipelineMetrics(BaseModel):
    total_articles_written: int | None = None
    backlog_count: int | None = None
    blocked_count: int | None = None
    oldest_backlog_age_days: int | None = None
    last_published_at: str | None = None
    last_7_runs: list[dict] = []


class TrafficPayload(BaseModel):
    configured: bool = False
    clicks: dict | None = None
    impressions: dict | None = None
    sessions: dict | None = None


class PipelineSyncItem(BaseModel):
    slug: str
    name: str
    url: str
    metrics: PipelineMetrics
    pipeline_alert_severity: str
    pipeline_alert_messages: list[dict] = []
    traffic: TrafficPayload
    traffic_alert_severity: str
    traffic_alert_messages: list[dict] = []
    gsc_site_url: str | None = None
    ga4_property_id: str | None = None


class SyncPayload(BaseModel):
    portfolio: list[PortfolioSyncItem] = []
    pipelines: list[PipelineSyncItem] = []
