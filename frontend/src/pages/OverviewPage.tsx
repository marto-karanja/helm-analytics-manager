import * as React from 'react'
import { Link } from 'react-router-dom'
import { SeverityBadge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { fetchProjects } from '@/lib/api'
import type { Project } from '@/lib/types'

export function OverviewPage() {
  const [projects, setProjects] = React.useState<Project[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch(() => setError('Failed to load projects.'))
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
          </Card>
        </Link>
      ))}
    </div>
  )
}
