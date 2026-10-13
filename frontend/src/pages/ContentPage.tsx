import * as React from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Newspaper } from 'lucide-react'
import { Link } from 'react-router-dom'
import { SeverityBadge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Table, TD, TH, THead, TR } from '@/components/ui/table'
import { fetchContentDashboard } from '@/lib/api'
import { AXIS_LINE, AXIS_TICK, CHART, TOOLTIP_PROPS } from '@/lib/chartTheme'
import { formatNumber } from '@/lib/traffic'
import type { ContentDashboard, ContentItem, ContentPoint } from '@/lib/types'
import { PageLoading } from '@/components/ui/skeleton'

function formatDays(days: number | null): string {
  if (days === null) return '—'
  if (days === 0) return 'Empty'
  if (days > 365) return '> 1 year'
  return `${days} d`
}

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="min-w-0">
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl sm:text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  )
}

/** A tiny inline line of one field over the snapshot history. */
function Spark({ points, field, label }: { points: ContentPoint[]; field: 'published' | 'queued'; label: string }) {
  const values = points.map((p) => p[field]).filter((v): v is number => v !== null)
  if (values.length < 2) return <span className="text-muted-foreground">—</span>
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const w = 72
  const h = 20
  const d = values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${((i / (values.length - 1)) * w).toFixed(1)} ${(h - 2 - ((v - min) / span) * (h - 4)).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={w} height={h} role="img" aria-label={`${label}: ${values[0]} to ${values[values.length - 1]}`} className="inline-block text-primary">
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

const COLUMNS = ['Site', 'Status', 'Published', 'In queue', 'Blocked', 'Per day', 'Queue lasts', 'Last published', 'Queue trend']

function ContentTable({ items }: { items: ContentItem[] }) {
  return (
    <Table>
      <THead>
        <tr>
          {COLUMNS.map((h) => (
            <TH key={h} numeric={h !== 'Site' && h !== 'Status'} sticky={h === 'Site'} className="whitespace-nowrap">
              {h}
            </TH>
          ))}
        </tr>
      </THead>
      <tbody>
        {items.map((i) => (
          <TR key={i.project_id}>
            <TD sticky className="whitespace-nowrap">
              <Link to={`/projects/${i.project_id}`} className="font-medium hover:underline">
                {i.name}
              </Link>
            </TD>
            <TD>
              <SeverityBadge severity={i.severity} />
            </TD>
            <TD numeric>{formatNumber(i.published)}</TD>
            <TD numeric className={i.queued === 0 ? 'font-medium text-destructive' : ''}>
              {formatNumber(i.queued)}
            </TD>
            <TD numeric>{formatNumber(i.blocked)}</TD>
            <TD numeric>{i.published_per_day === null ? '—' : i.published_per_day.toFixed(1)}</TD>
            <TD numeric>{formatDays(i.days_to_clear_queue)}</TD>
            <TD numeric className="whitespace-nowrap">
              {formatDate(i.last_published_at)}
            </TD>
            <TD numeric>
              <Spark points={i.history} field="queued" label={`${i.name} queue`} />
            </TD>
          </TR>
        ))}
      </tbody>
    </Table>
  )
}

function ShareChart({ items }: { items: ContentItem[] }) {
  const data = items.map((i) => ({ name: i.name, Published: i.published ?? 0, 'In queue': i.queued ?? 0 }))
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 36 + 48)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" horizontal={false} />
        <XAxis type="number" tick={AXIS_TICK} stroke={AXIS_LINE} allowDecimals={false} />
        <YAxis type="category" dataKey="name" width={160} tick={AXIS_TICK} stroke={AXIS_LINE} />
        <Tooltip {...TOOLTIP_PROPS} cursor={{ fill: 'var(--color-muted)' }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Published" stackId="a" fill={CHART.indigo} isAnimationActive={false} />
        <Bar dataKey="In queue" stackId="a" fill={CHART.orange} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ContentPage() {
  const [data, setData] = React.useState<ContentDashboard | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    fetchContentDashboard()
      .then(setData)
      .catch(() => setError('Failed to load the content dashboard.'))
  }, [])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) return <PageLoading />

  const { totals, items } = data
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Content</h1>
        <p className="text-sm text-muted-foreground">
          Articles each publishing pipeline has written, and how many are still waiting in its queue. Counts come from the
          latest sync from the pipelines; the rate is measured over the last 4 weeks of syncs.
        </p>
      </div>

      {items.length === 0 ? (
        <EmptyState
          icon={<Newspaper size={24} />}
          title="No publishing pipelines have synced yet"
          description="Once a pipeline pushes its counts, its published articles and queue appear here."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <Kpi label="Published" value={formatNumber(totals.published)} hint={`${totals.pipelines} pipelines`} />
            <Kpi
              label="In queue"
              value={formatNumber(totals.queued)}
              hint={totals.pipelines_empty > 0 ? `${totals.pipelines_empty} empty` : 'none empty'}
            />
            <Kpi label="Blocked" value={formatNumber(totals.blocked)} />
            <Kpi
              label="Publishing rate"
              value={`${totals.published_per_day.toFixed(1)} / day`}
              hint={totals.days_to_clear_queue === null ? 'queue length unknown' : `queue lasts about ${formatDays(totals.days_to_clear_queue)}`}
            />
          </div>

          <ContentTable items={items} />

          <Card>
            <CardHeader>
              <CardTitle>Published and queued by site</CardTitle>
            </CardHeader>
            <CardContent>
              <ShareChart items={items} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
