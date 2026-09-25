import type { TrafficDay, TrafficTrend } from './types'

export const STALE_AFTER_HOURS = 48

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toLocaleString()
}

export function formatPct(trend: TrafficTrend | null): string | null {
  if (!trend || trend.pct_change === null) return null
  return `${trend.pct_change > 0 ? '+' : ''}${trend.pct_change}%`
}

export function isStale(lastCollectedAt: string | null, now = Date.now()): boolean {
  if (!lastCollectedAt) return false
  return now - new Date(lastCollectedAt).getTime() > STALE_AFTER_HOURS * 3600 * 1000
}

export function formatCollectedAt(lastCollectedAt: string | null): string {
  return lastCollectedAt ? new Date(lastCollectedAt).toLocaleString() : 'never'
}

function parseDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function formatDay(iso: string): string {
  return parseDay(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function toIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// Days the source skipped get an all-null row so charts draw a gap instead of joining across it.
export function fillGaps(days: TrafficDay[]): TrafficDay[] {
  if (days.length === 0) return []
  const byDate = new Map(days.map((d) => [d.metric_date, d]))
  const filled: TrafficDay[] = []
  const last = parseDay(days[days.length - 1].metric_date)
  for (let d = parseDay(days[0].metric_date); d <= last; d.setDate(d.getDate() + 1)) {
    const iso = toIso(d)
    filled.push(
      byDate.get(iso) ?? {
        metric_date: iso,
        clicks: null,
        impressions: null,
        ctr: null,
        avg_position: null,
        sessions: null,
        engaged_sessions: null,
      },
    )
  }
  return filled
}
