import * as React from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Badge, SeverityBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { fetchTraffic } from '@/lib/api'
import {
  fillGaps,
  formatCollectedAt,
  formatDay,
  formatNumber,
  formatPct,
  isStale,
} from '@/lib/traffic'
import type { ProjectDetail, TrafficData, TrafficDay, TrafficTrend } from '@/lib/types'

const RANGES = [
  { days: 28, label: '28 days' },
  { days: 90, label: '90 days' },
  { days: 180, label: '6 months' },
  { days: 480, label: '16 months' },
] as const

const AXIS_TICK = { fontSize: 12, fill: 'var(--color-muted-foreground)' }
const TOOLTIP_STYLE = {
  background: 'var(--color-card)',
  border: '1px solid var(--color-border)',
  borderRadius: 6,
  fontSize: 12,
}

interface Series {
  key: keyof TrafficDay
  label: string
  color: string
  dashed?: boolean
}

function MetricChart({
  title,
  hint,
  data,
  series,
  reversed = false,
  decimals = 0,
}: {
  title: string
  hint?: string
  data: TrafficDay[]
  series: Series[]
  reversed?: boolean
  decimals?: number
}) {
  const hasData = series.some((s) => data.some((d) => d[s.key] !== null))
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        {series.length > 1 && (
          <ul className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs text-muted-foreground">
            {series.map((s) => (
              <li key={s.key} className="flex items-center gap-1.5">
                <svg width="18" height="6" aria-hidden="true">
                  <line
                    x1="0"
                    y1="3"
                    x2="18"
                    y2="3"
                    stroke={s.color}
                    strokeWidth="2"
                    strokeDasharray={s.dashed ? '4 3' : undefined}
                  />
                </svg>
                {s.label}
              </li>
            ))}
          </ul>
        )}
      </CardHeader>
      <CardContent>
        {!hasData ? (
          <p className="py-8 text-center text-sm text-muted-foreground">No data for this source yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis
                dataKey="metric_date"
                tickFormatter={formatDay}
                tick={AXIS_TICK}
                stroke="var(--color-border)"
                minTickGap={32}
              />
              <YAxis
                tick={AXIS_TICK}
                stroke="var(--color-border)"
                reversed={reversed}
                allowDecimals={decimals > 0}
                domain={reversed ? ['auto', 'auto'] : [0, 'auto']}
                width={48}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelFormatter={(label) => formatDay(String(label))}
                formatter={(value) => (typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: decimals }) : '—')}
                labelStyle={{ color: 'var(--color-card-foreground)' }}
                itemStyle={{ color: 'var(--color-card-foreground)' }}
                cursor={{ stroke: 'var(--color-border)' }}
              />
              {series.map((s) => (
                <Line
                  key={s.key}
                  name={s.label}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={2}
                  strokeDasharray={s.dashed ? '4 3' : undefined}
                  dot={false}
                  connectNulls={false}
                  isAnimationActive={false}
                  activeDot={{ r: 4, stroke: 'var(--color-card)', strokeWidth: 2 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}

function TrendTile({ label, trend }: { label: string; trend: TrafficTrend | null }) {
  const pct = formatPct(trend)
  return (
    <div>
      <p className="text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold">{trend ? formatNumber(trend.recent) : '—'}</p>
      <p
        className={
          trend?.pct_change == null
            ? 'text-muted-foreground'
            : trend.pct_change < 0
              ? 'text-destructive'
              : 'text-severity-green'
        }
      >
        {pct ?? (trend ? 'no prior week' : 'not collected')}
      </p>
    </div>
  )
}

function DataTable({ days }: { days: TrafficDay[] }) {
  const rows = [...days].reverse()
  return (
    <div className="max-h-96 overflow-auto rounded-md border border-border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card text-left text-muted-foreground">
          <tr>
            {['Date', 'Clicks', 'Impressions', 'CTR', 'Avg position', 'Sessions', 'Engaged'].map((h) => (
              <th key={h} className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.metric_date} className="border-t border-border">
              <td className="px-3 py-1.5">{d.metric_date}</td>
              <td className="px-3 py-1.5">{formatNumber(d.clicks)}</td>
              <td className="px-3 py-1.5">{formatNumber(d.impressions)}</td>
              <td className="px-3 py-1.5">{d.ctr === null ? '—' : `${(d.ctr * 100).toFixed(1)}%`}</td>
              <td className="px-3 py-1.5">{d.avg_position === null ? '—' : d.avg_position.toFixed(1)}</td>
              <td className="px-3 py-1.5">{formatNumber(d.sessions)}</td>
              <td className="px-3 py-1.5">{formatNumber(d.engaged_sessions)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TrafficSection({ project, isDemo }: { project: ProjectDetail; isDemo: boolean }) {
  const [days, setDays] = React.useState<number>(90)
  const [view, setView] = React.useState<'charts' | 'table'>('charts')
  const [traffic, setTraffic] = React.useState<TrafficData | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    setError(null)
    fetchTraffic(project.id, days)
      .then((data) => !cancelled && setTraffic(data))
      .catch(() => !cancelled && setError('Failed to load traffic data.'))
    return () => {
      cancelled = true
    }
  }, [project.id, days])

  // A /projects/:id#traffic deep link scrolls before the charts have laid out, so scroll again once data is in.
  const scrolledToHash = React.useRef(false)
  React.useEffect(() => {
    if (traffic && !scrolledToHash.current && window.location.hash === '#traffic') {
      scrolledToHash.current = true
      document.getElementById('traffic')?.scrollIntoView()
    }
  }, [traffic])

  const snapshot = project.traffic_snapshots[0]
  const connected = Boolean(project.gsc_site_url || project.ga4_property_id || snapshot?.configured)
  const chartData = React.useMemo(() => fillGaps(traffic?.days ?? []), [traffic])
  const stale = !isDemo && isStale(project.traffic_last_collected_at)

  if (!connected) {
    return (
      <Card id="traffic">
        <CardHeader>
          <CardTitle className="text-sm">Search traffic</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm text-muted-foreground">
          <p>Search Console / Analytics not connected for this site.</p>
          {!isDemo && (
            <p>
              Connect it on the server with{' '}
              <code className="rounded bg-muted px-1.5 py-0.5 text-foreground">
                python -m app.cli set-analytics {project.slug} --gsc sc-domain:example.com --ga4 properties/123456789
              </code>
              .
            </p>
          )}
        </CardContent>
      </Card>
    )
  }

  const alerts = snapshot?.alert_messages ?? []

  return (
    <section id="traffic" className="flex scroll-mt-6 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">Search traffic</h2>
          {snapshot && <SeverityBadge severity={snapshot.alert_severity} />}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Last collected {formatCollectedAt(project.traffic_last_collected_at)}</span>
          {stale && <Badge variant="yellow">Stale</Badge>}
        </div>
      </div>

      {snapshot?.configured && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Last 7 days vs. the 7 before</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-3">
              <TrendTile label="Clicks" trend={snapshot.clicks} />
              <TrendTile label="Impressions" trend={snapshot.impressions} />
              <TrendTile label="Sessions" trend={snapshot.sessions} />
            </div>
            {alerts.length > 0 && (
              <ul className="flex flex-col gap-1.5 text-sm">
                {alerts.map((a) => (
                  <li key={a.message} className="flex items-start gap-2">
                    <SeverityBadge severity={a.severity} />
                    <span>{a.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <Button
              key={r.days}
              size="sm"
              variant={days === r.days ? 'default' : 'outline'}
              aria-pressed={days === r.days}
              onClick={() => setDays(r.days)}
            >
              {r.label}
            </Button>
          ))}
        </div>
        <div className="flex gap-1" role="group" aria-label="View">
          <Button size="sm" variant={view === 'charts' ? 'default' : 'outline'} aria-pressed={view === 'charts'} onClick={() => setView('charts')}>
            Charts
          </Button>
          <Button size="sm" variant={view === 'table' ? 'default' : 'outline'} aria-pressed={view === 'table'} onClick={() => setView('table')}>
            Table
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!traffic && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
      {traffic && traffic.days.length === 0 && (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            No data collected yet. The collector runs daily; the first pull backfills up to 16 months of history.
          </CardContent>
        </Card>
      )}

      {traffic && traffic.days.length > 0 && view === 'table' && <DataTable days={chartData} />}

      {traffic && traffic.days.length > 0 && view === 'charts' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <MetricChart
            title="Clicks"
            data={chartData}
            series={[{ key: 'clicks', label: 'Clicks', color: 'var(--color-primary)' }]}
          />
          <MetricChart
            title="Impressions"
            data={chartData}
            series={[{ key: 'impressions', label: 'Impressions', color: 'var(--color-primary)' }]}
          />
          <MetricChart
            title="Sessions"
            hint="From Google Analytics 4. Today's value is partial."
            data={chartData}
            series={[
              { key: 'sessions', label: 'Sessions', color: 'var(--color-primary)' },
              { key: 'engaged_sessions', label: 'Engaged sessions', color: 'var(--color-muted-foreground)', dashed: true },
            ]}
          />
          <MetricChart
            title="Average position"
            hint="Lower is better, so the axis is flipped."
            data={chartData}
            series={[{ key: 'avg_position', label: 'Average position', color: 'var(--color-primary)' }]}
            reversed
            decimals={1}
          />
        </div>
      )}
    </section>
  )
}
