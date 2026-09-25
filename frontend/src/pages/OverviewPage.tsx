import * as React from 'react'
import { Link } from 'react-router-dom'
import { SeverityBadge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { fetchProjects, fetchTrafficOverview } from '@/lib/api'
import { formatNumber, formatPct } from '@/lib/traffic'
import type { Project, TrafficOverviewItem } from '@/lib/types'

export function OverviewPage() {
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [traffic, setTraffic] = React.useState<Record<string, TrafficOverviewItem>>({})
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch(() => setError('Failed to load projects.'))
    // Traffic is a bonus on the cards: if it fails to load, the cards simply omit it.
    fetchTrafficOverview()
      .then((items) => setTraffic(Object.fromEntries(items.map((i) => [i.project_id, i]))))
      .catch(() => undefined)
  }, [])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!projects) return <p className="text-sm text-muted-foreground">Loading…</p>

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map((project) => (
        <Link key={project.id} to={`/projects/${project.id}`}>
          <Card className="h-full transition-shadow hover:shadow-md">
            <CardHeader className="flex-row items-start justify-between space-y-0">
              <div>
                <CardTitle>{project.name}</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">{project.category}</p>
              </div>
              {project.is_pipeline && <SeverityBadge severity={project.latest_alert_severity} />}
            </CardHeader>
            <CardContent className="flex items-center justify-between text-sm text-muted-foreground">
              <span className="truncate">{project.url}</span>
              <span className="shrink-0 pl-2">
                {project.open_task_count} open task{project.open_task_count === 1 ? '' : 's'}
              </span>
            </CardContent>
            {project.is_pipeline && <TrafficLine item={traffic[project.id]} />}
          </Card>
        </Link>
      ))}
    </div>
  )
}

function TrafficLine({ item }: { item: TrafficOverviewItem | undefined }) {
  if (!item) return null
  if (!item.configured) {
    return <p className="px-4 pb-4 text-xs text-muted-foreground">Search traffic not connected</p>
  }
  const pct = formatPct(item.clicks)
  return (
    <p className="flex items-center gap-2 px-4 pb-4 text-xs text-muted-foreground">
      <span>
        Clicks (7d): <span className="font-medium text-foreground">{formatNumber(item.clicks?.recent)}</span>
      </span>
      {pct && <span className={item.clicks!.pct_change! < 0 ? 'text-destructive' : 'text-severity-green'}>{pct}</span>}
      {item.alert_severity && item.alert_severity !== 'green' && <SeverityBadge severity={item.alert_severity} />}
    </p>
  )
}
