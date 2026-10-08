import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _project_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class SitemapUrl(Base):
    """Canonical URL list: every <loc> found by walking the project's sitemaps."""

    __tablename__ = "sitemap_urls"
    __table_args__ = (UniqueConstraint("project_id", "url", name="uq_sitemap_urls_project_url"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    url: Mapped[str] = mapped_column(Text)
    source_sitemap: Mapped[str | None] = mapped_column(Text, nullable=True)
    lastmod: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = _now()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UrlInspection(Base):
    """Append-only history of URL Inspection API results."""

    __tablename__ = "url_inspections"
    __table_args__ = (Index("ix_url_inspections_project_url_at", "project_id", "url", "inspected_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    url: Mapped[str] = mapped_column(Text)
    inspected_at: Mapped[datetime] = _now()
    verdict: Mapped[str | None] = mapped_column(String(50), nullable=True)
    coverage_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexing_state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    robots_txt_state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    page_fetch_state: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_crawl_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crawled_as: Mapped[str | None] = mapped_column(String(50), nullable=True)
    google_canonical: Mapped[str | None] = mapped_column(Text, nullable=True)


class PageSignal(Base):
    """Content signals from fetching the page itself; one row per fetch."""

    __tablename__ = "page_signals"
    __table_args__ = (Index("ix_page_signals_project_url_at", "project_id", "url", "fetched_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    url: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = _now()
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h1_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    headings: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # H2 texts, keyword-generator seeds
    internal_links: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical: Mapped[str | None] = mapped_column(Text, nullable=True)
    noindex: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="http")  # http | crawler
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SitemapStatus(Base):
    """Latest `sitemaps.list` answer per project sitemap, overwritten each walk."""

    __tablename__ = "sitemap_status"
    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_sitemap_status_project_path"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    path: Mapped[str] = mapped_column(Text)
    last_submitted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_downloaded: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    submitted_urls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexed_urls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[datetime] = _now()


class IndexingSnapshot(Base):
    """Daily per-project issue counts, so the Indexing tab can chart indexed over time."""

    __tablename__ = "indexing_snapshots"
    __table_args__ = (UniqueConstraint("project_id", "snapshot_date", name="uq_indexing_snapshots_project_date"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    snapshot_date: Mapped[date] = mapped_column(Date)
    total_urls: Mapped[int] = mapped_column(Integer, default=0)
    counts: Mapped[dict] = mapped_column(JSONB)  # {issue: n}


class GscQueryRollup(Base):
    __tablename__ = "gsc_query_rollups"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    query: Mapped[str] = mapped_column(Text, primary_key=True)
    page: Mapped[str] = mapped_column(Text, primary_key=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    position_avg: Mapped[float] = mapped_column(Float, default=0.0)


class WeeklyDigest(Base):
    """Frozen per-project weekly snapshot for the digest report."""

    __tablename__ = "weekly_digests"
    __table_args__ = (UniqueConstraint("project_id", "week_start", name="uq_weekly_digests_project_week"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    week_start: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()
    payload: Mapped[dict] = mapped_column(JSONB)


class KeywordRun(Base):
    __tablename__ = "keyword_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)


class KeywordCandidate(Base):
    __tablename__ = "keyword_candidates"
    __table_args__ = (UniqueConstraint("project_id", "keyword", name="uq_keyword_candidates_project_keyword"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("keyword_runs.id", ondelete="SET NULL"), nullable=True)
    keyword: Mapped[str] = mapped_column(Text)
    cluster_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cluster_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_is_bucket: Mapped[bool] = mapped_column(Boolean, default=False)
    competition: Mapped[float | None] = mapped_column(Float, nullable=True)
    impressions_proxy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    demand_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    demand_source: Mapped[str] = mapped_column(String(20), default="none")  # gsc | kp_exact | kp_bucket | none
    gap: Mapped[str | None] = mapped_column(String(30), nullable=True)  # striking_distance | no_page | ranking
    score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(10), default="llm")  # gsc | llm | manual
    status: Mapped[str] = mapped_column(String(10), default="proposed")  # proposed|accepted|rejected|written
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KeywordMetric(Base):
    """Cache of Keyword Planner answers: volumes move slowly, so a keyword is looked up at most once a quarter."""

    __tablename__ = "keyword_metrics"
    __table_args__ = (UniqueConstraint("keyword", "geo", "language", "provider", name="uq_keyword_metrics_key"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    keyword: Mapped[str] = mapped_column(Text)
    geo: Mapped[str] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(30))
    avg_monthly_searches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_bucket: Mapped[bool] = mapped_column(Boolean, default=False)
    competition_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_series: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = _now()


class LlmSpend(Base):
    """Per-call ledger so the daily LLM cap is enforced from recorded cost, not estimates."""

    __tablename__ = "llm_spend"

    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = _now()
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class McpToken(Base):
    __tablename__ = "mcp_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    label: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex; plaintext never stored
    scope: Mapped[str] = mapped_column(String(10), default="read")  # read | write
    # Project slugs this token may see; None means every project (the owner's own tokens).
    project_slugs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _now()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class McpCall(Base):
    __tablename__ = "mcp_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    token_label: Mapped[str] = mapped_column(String(100))
    tool: Mapped[str] = mapped_column(String(100))
    args_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))  # ok | error | denied | rate_limited


class RollupRequest(Base):
    """A manual "refresh rankings": the on-demand alternative to the weekly query rollup. Queued by the web
    container or the MCP server and run by the collector, which holds the Google credentials."""

    __tablename__ = "rollup_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    requested_at: Mapped[datetime] = _now()
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class InspectRequest(Base):
    """A manual "Inspect now". The web container holds no Google credentials, so it queues the request and
    the collector, which does, picks it up on its next tick."""

    __tablename__ = "inspect_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    url: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = _now()
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
