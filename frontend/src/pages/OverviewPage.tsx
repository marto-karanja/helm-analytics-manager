import * as React from 'react'
import { Link } from 'react-router-dom'
import { Sparkline } from '@/components/Sparkline'
import { TrendChip } from '@/components/TrendChip'
import { SeverityBadge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { LoadingBlock, Skeleton } from '@/components/ui/skeleton'
import { fetchProjects, fetchTrafficOverview } from '@/lib/api'
import { fetchIndexingOverview } from '@/lib/indexingApi'
import type { IndexingOverviewItem } from '@/lib/indexingTypes'
import { formatNumber } from '@/lib/traffic'
import type { Project, TrafficOverviewItem } from '@/lib/types'

/** A stable hue per project, so each card keeps the same avatar colour. */
function hueFor(slug: string): number {
  let h = 0
  for (const ch of slug) h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
}

function Avatar({ name, slug }: { name: string; slug: string }) {
  return (
    <span
      aria-hidden
      className="grid size-9 shrink-0 place-items-center rounded-lg text-sm font-semibold text-white"
      style={{ background: `oklch(0.5 0.14 ${hueFor(slug)})` }}
    >
      {name.trim().charAt(0).toUpperCase()}
    </span>
  )
}

type Group = 'attention' | 'healthy' | 'other'

function worstSeverity(...values: (string | null | undefined)[]): string | null {
  if (values.includes('red')) return 'red'
  if (values.includes('yellow')) return 'yellow'
  if (values.includes('green')) return 'green'
  return null
}

function groupOf(project: Project, traffic: TrafficOverviewItem | undefined): Group {
  if (!project.is_pipeline) return 'other'
  const severity = worstSeverity(project.latest_alert_severity, traffic?.alert_severity)
  return severity === 'red' || severity === 'yellow' ? 'attention' : 'healthy'
}

function SummaryTile({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <Card className="min-w-0">
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <p className="text-xl font-semibold tabular-nums sm:text-2xl">{value}</p>
          {children}
        </div>
      </CardContent>
    </Card>
  )
}

function SummaryStrip({ projects, traffic, indexing }: { projects: Project[]; traffic: Record<string, TrafficOverviewItem>; indexing: Record<string, IndexingOverviewItem> }) {
  const pipelines = projects.filter((p) => p.is_pipeline)
  const connected = pipelines.map((p) => traffic[p.id]).filter((t): t is TrafficOverviewItem => !!t?.clicks)
  const recent = connected.reduce((n, t) => n + (t.clicks?.recent ?? 0), 0)
  const prior = connected.reduce((n, t) => n + (t.clicks?.prior ?? 0), 0)
  const pct = prior > 0 ? Math.round(((recent - prior) / prior) * 1000) / 10 : null
  const indexedValues = pipelines.map((p) => indexing[p.id]?.indexed_percent).filter((v): v is number => typeof v === 'number')
  const avgIndexed = indexedValues.length ? Math.round((indexedValues.reduce((a, b) => a + b, 0) / indexedValues.length) * 10) / 10 : null
  const openAlerts = pipelines.filter((p) => {
    const s = worstSeverity(p.latest_alert_severity, traffic[p.id]?.alert_severity)
    return s === 'red' || s === 'yellow'
  }).length
  const needWork = pipelines.filter((p) => {
    const i = indexing[p.id]
    return !!i && i.thin + i.crawled_not_indexed > 0
  }).length

  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" aria-label="Portfolio summary">
      <SummaryTile label="Clicks, last 7 days" value={connected.length ? formatNumber(recent) : '—'}>
        <TrendChip pct={pct} />
      </SummaryTile>
      <SummaryTile label="Average indexed" value={avgIndexed === null ? '—' : `${avgIndexed}%`} />
      <SummaryTile label="Sites with alerts" value={String(openAlerts)} />
      <SummaryTile label="Sites needing work" value={String(needWork)} />
    </div>
  )
}

function ProjectCard({ project, traffic, indexing }: { project: Project; traffic?: TrafficOverviewItem; indexing?: IndexingOverviewItem }) {
  const clicks = traffic?.configured ? traffic.clicks : null
  const hasIndexing = !!indexing && indexing.total_urls > 0
  const problems = indexing ? indexing.thin + indexing.crawled_not_indexed : 0
  const severity = worstSeverity(project.latest_alert_severity, traffic?.alert_severity)

  return (
    <Link to={`/projects/${project.id}`} className="group block rounded-lg focus-visible:outline-offset-4">
      <Card className="h-full transition-[box-shadow,transform] duration-150 group-hover:-translate-y-px group-hover:shadow-card-hover">
        <CardContent className="flex h-full flex-col gap-3 p-4">
          <div className="flex items-start gap-3">
            <Avatar name={project.name} slug={project.slug} />
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-sm font-semibold">{project.name}</h3>
              <p className="truncate text-xs text-muted-foreground">{project.url}</p>
            </div>
            {project.is_pipeline && <SeverityBadge severity={severity} />}
          </div>

          {project.is_pipeline ? (
            clicks ? (
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-xs text-muted-foreground">Clicks (7d)</p>
                  <div className="flex items-center gap-2">
                    <span className="text-2xl font-semibold tabular-nums">{formatNumber(clicks.recent)}</span>
                    <TrendChip pct={clicks.pct_change} />
                  </div>
                </div>
                <Sparkline values={traffic?.clicks_series ?? []} label={`${project.name} clicks, last 28 days`} />
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">Search traffic not connected</p>
            )
          ) : (
            <p className="truncate text-sm text-muted-foreground">{project.category}</p>
          )}

          <div className="mt-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {hasIndexing && (
              <>
                <span>
                  Indexed: <span className="font-medium tabular-nums text-foreground">{indexing!.indexed_percent === null ? '—' : `${indexing!.indexed_percent}%`}</span>
                </span>
                <span title="Thin pages plus pages Google crawled but did not index">
                  Needs work: <span className={`font-medium tabular-nums ${problems > 0 ? 'text-foreground' : ''}`}>{problems}</span>
                </span>
                {indexing!.pending_keywords > 0 && (
                  <span>
                    Keywords to review: <span className="font-medium tabular-nums text-foreground">{indexing!.pending_keywords}</span>
                  </span>
                )}
              </>
            )}
            <span className="ml-auto tabular-nums">
              {project.open_task_count} open task{project.open_task_count === 1 ? '' : 's'}
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
    </section>
  )
}

function OverviewSkeleton() {
  return (
    <LoadingBlock>
      <div className="flex flex-col gap-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      </div>
    </LoadingBlock>
  )
}

export function OverviewPage() {
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [traffic, setTraffic] = React.useState<Record<string, TrafficOverviewItem>>({})
  const [indexing, setIndexing] = React.useState<Record<string, IndexingOverviewItem>>({})
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    // Indexing and traffic are bonuses on the cards: if either fails to load, the cards simply omit it.
    fetchIndexingOverview()
      .then((items) => setIndexing(Object.fromEntries(items.map((i) => [i.project_id, i]))))
      .catch(() => undefined)
    fetchProjects()
      .then(setProjects)
      .catch(() => setError('Failed to load projects.'))
    fetchTrafficOverview()
      .then((items) => setTraffic(Object.fromEntries(items.map((i) => [i.project_id, i]))))
      .catch(() => undefined)
  }, [])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!projects) return <OverviewSkeleton />

  const groups: Record<Group, Project[]> = { attention: [], healthy: [], other: [] }
  for (const p of projects) groups[groupOf(p, traffic[p.id])].push(p)

  const render = (list: Project[]) =>
    list.map((p) => <ProjectCard key={p.id} project={p} traffic={traffic[p.id]} indexing={indexing[p.id]} />)

  return (
    <div className="flex flex-col gap-8">
      <SummaryStrip projects={projects} traffic={traffic} indexing={indexing} />
      {groups.attention.length > 0 && (
        <Section title="Needs attention" hint={`${groups.attention.length} site${groups.attention.length === 1 ? '' : 's'}`}>
          {render(groups.attention)}
        </Section>
      )}
      {groups.healthy.length > 0 && <Section title="Healthy">{render(groups.healthy)}</Section>}
      {groups.other.length > 0 && <Section title="Other projects">{render(groups.other)}</Section>}
    </div>
  )
}
