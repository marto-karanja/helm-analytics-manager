// Types for indexing analysis, keywords, reports, settings and MCP tokens.

export type IndexIssue =
  | 'fetch_error'
  | 'blocked'
  | 'duplicate_risk'
  | 'thin'
  | 'crawled_not_indexed'
  | 'discovered_not_indexed'
  | 'indexed'
  | 'unknown'

export interface InspectionBudget {
  budget: number
  spent_today: number
  queued: number
  remaining: number
}

export interface IndexingSummary {
  total: number
  counts: Record<IndexIssue, number>
  indexed_percent: number | null
  thin_word_threshold: number
  history: { date: string; total: number; counts: Partial<Record<IndexIssue, number>> }[]
  last_sitemap_walk_at: string | null
  last_inspection_at: string | null
  budget: InspectionBudget
  has_search_console: boolean
}

export interface IndexedUrl {
  id: string
  url: string
  lastmod: string | null
  issue: IndexIssue
  verdict: string | null
  coverage_state: string | null
  last_crawl_time: string | null
  inspected_at: string | null
  word_count: number | null
  title: string | null
  http_status: number | null
}

export interface IndexedUrlList {
  total: number
  items: IndexedUrl[]
}

export interface UrlDetail {
  id: string
  url: string
  issue: IndexIssue | null
  lastmod: string | null
  first_seen_at: string
  inspections: {
    inspected_at: string
    verdict: string | null
    coverage_state: string | null
    indexing_state: string | null
    robots_txt_state: string | null
    page_fetch_state: string | null
    last_crawl_time: string | null
    crawled_as: string | null
    google_canonical: string | null
  }[]
  signals: {
    fetched_at: string
    http_status: number | null
    title: string | null
    meta_description: string | null
    word_count: number | null
    h1_count: number | null
    h2_count: number | null
    internal_links: number | null
    canonical: string | null
    noindex: boolean
    source: string
    error: string | null
  }[]
}

export interface SitemapInfo {
  has_search_console: boolean
  sitemaps: {
    path: string
    last_submitted: string | null
    last_downloaded: string | null
    is_pending: boolean
    errors: number
    warnings: number
    submitted_urls: number | null
    indexed_urls: number | null
    urls_found_by_helm: number
    fetched_at: string
  }[]
  urls_by_source: { sitemap: string | null; urls: number }[]
}

export interface IndexingOverviewItem {
  project_id: string
  slug: string
  total_urls: number
  indexed_percent: number | null
  thin: number
  crawled_not_indexed: number
  pending_keywords: number
}

export type CandidateStatus = 'proposed' | 'accepted' | 'rejected' | 'written'
export type DecidableStatus = 'proposed' | 'accepted' | 'rejected'

export interface KeywordCandidate {
  id: string
  keyword: string
  cluster_id: string | null
  cluster_label: string | null
  intent: string | null
  volume: number | null
  volume_is_bucket: boolean
  competition: number | null
  impressions_proxy: number | null
  position_avg: number | null
  demand_est: number | null
  demand_source: 'gsc' | 'kp_exact' | 'kp_bucket' | 'none'
  gap: string | null
  score: number
  source: string
  status: CandidateStatus
  target_url: string | null
  decided_at: string | null
}

export interface KeywordRun {
  id: string
  started_at: string
  finished_at: string | null
  status: 'running' | 'ok' | 'error'
  model: string | null
  prompt_version: string | null
  source_counts: Record<string, number | string> | null
  error: string | null
  cost_usd: number | null
}

export interface KeywordList {
  candidates: KeywordCandidate[]
  counts: Record<CandidateStatus, number>
  runs: KeywordRun[]
  volume_source: string
  llm_configured: boolean
}

export type ReportCell = string | number | boolean | null

export interface ReportMeta {
  as_of: string
  /** current: live now; stored: an exact record from that date; reconstructed: rebuilt from history; none: no history. */
  basis: 'current' | 'stored' | 'reconstructed' | 'none'
  available_from: string | null
  available_to: string | null
  history: string
  note: string | null
  out_of_range: boolean
}

export interface ReportData {
  name: string
  columns: string[]
  rows: ReportCell[][]
  meta: ReportMeta
}

export interface CompareData {
  name: string
  columns: string[]
  rows: ReportCell[][]
  summary: { new: number; gone: number; changed: number; same: number }
  meta: { a: ReportMeta; b: ReportMeta; notes: string[]; change_column: string }
}

export interface ReportCatalogItem {
  name: string
  label: string
  blurb: string
  kind: 'as_of' | 'range'
  compare_keys: string[]
  history: string
}

export interface ReportAvailability {
  today: string
  reports: Record<string, { label: string; kind: 'as_of' | 'range'; from: string | null; to: string | null; history: string }>
}

export interface ReportQuery {
  project?: string
  as_of?: string
  days?: number
  granularity?: string
  /** Compare mode: the two dates, A (earlier) and B. */
  a?: string
  b?: string
  changed_only?: boolean
}

export interface SettingsData {
  values: {
    inspection_budget: number
    inspection_budget_split: Record<string, number>
    thin_word_threshold: number
    scoring_weights: Record<'demand' | 'gap' | 'relevance' | 'competition', number>
    volume_source: 'gsc_proxy' | 'keyword_planner'
    llm_daily_cap_usd: number
  }
  descriptions: Record<string, string>
  limits: { inspection_ceiling: number; volume_sources: string[] }
  editable: boolean
}

export interface McpToken {
  id: string
  label: string
  scope: 'read' | 'write'
  /** null means the token sees every project. */
  project_slugs: string[] | null
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface RankedPage {
  url: string
  position: number | null
  position_prior: number | null
  /** Positive when the page moved up. */
  position_change: number | null
  clicks: number
  impressions: number
  ctr: number | null
  query_count: number
  top_queries: { query: string; position: number | null; clicks: number; impressions: number }[]
  indexing: string | null
  coverage_state: string | null
}

export interface Rankings {
  project: string
  note?: string
  window?: { weeks: number; first_week_start: string; latest_week_start: string }
  last_refreshed_at: string | null
  last_weekly_run_at: string | null
  last_manual_refresh_at: string | null
  refresh_pending: boolean
  total_pages?: number
  returned?: number
  pages: RankedPage[]
}
