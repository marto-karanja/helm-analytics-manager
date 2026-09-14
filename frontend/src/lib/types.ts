export interface Project {
  id: string
  slug: string
  name: string
  category: string
  url: string
  local_repo: string | null
  operational_signals: string | null
  last_updated: string | null
  goals: string | null
  current_status: string | null
  blockers: string | null
  priority_notes: string | null
  is_pipeline: boolean
  pipeline_task_name: string | null
  gsc_site_url: string | null
  ga4_property_id: string | null
  created_at: string
  updated_at: string
  latest_alert_severity: string | null
  open_task_count: number
}

export interface Task {
  id: string
  project_id: string
  title: string
  status: 'todo' | 'in_progress' | 'done'
  priority: 'low' | 'normal' | 'high'
  created_at: string
  updated_at: string
}

export interface PipelineSnapshot {
  id: string
  synced_at: string
  total_articles_written: number | null
  backlog_count: number | null
  blocked_count: number | null
  oldest_backlog_age_days: number | null
  last_published_at: string | null
  last_7_runs: { start: string; end: string; exit_code: number | null; failed: boolean }[] | null
  alert_severity: string | null
  alert_messages: { severity: string; message: string }[] | null
}

export interface TrafficSnapshot {
  id: string
  synced_at: string
  configured: boolean
  clicks: { recent: number; prior: number; pct_change: number | null } | null
  impressions: { recent: number; prior: number; pct_change: number | null } | null
  sessions: { recent: number; prior: number; pct_change: number | null } | null
  alert_severity: string | null
  alert_messages: { severity: string; message: string }[] | null
}

export interface ProjectDetail extends Project {
  tasks: Task[]
  pipeline_snapshots: PipelineSnapshot[]
  traffic_snapshots: TrafficSnapshot[]
}
