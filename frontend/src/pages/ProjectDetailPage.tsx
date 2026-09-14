import * as React from 'react'
import { useParams } from 'react-router-dom'
import { BacklogChart } from '@/components/BacklogChart'
import { TaskBoard } from '@/components/TaskBoard'
import { SeverityBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label, Textarea } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'
import { fetchProject, updateProject } from '@/lib/api'
import type { ProjectDetail } from '@/lib/types'

const EDITABLE_FIELDS = [
  { key: 'goals', label: 'Goals' },
  { key: 'current_status', label: 'Current status' },
  { key: 'blockers', label: 'Blockers' },
  { key: 'priority_notes', label: 'Priority notes' },
] as const

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const [project, setProject] = React.useState<ProjectDetail | null>(null)
  const [drafts, setDrafts] = React.useState<Record<string, string>>({})
  const [saving, setSaving] = React.useState<string | null>(null)
  const { isDemo } = useAuth()

  React.useEffect(() => {
    if (!projectId) return
    fetchProject(projectId).then((p) => {
      setProject(p)
      setDrafts({
        goals: p.goals ?? '',
        current_status: p.current_status ?? '',
        blockers: p.blockers ?? '',
        priority_notes: p.priority_notes ?? '',
      })
    })
  }, [projectId])

  async function handleSave(field: (typeof EDITABLE_FIELDS)[number]['key']) {
    if (!project) return
    setSaving(field)
    try {
      const updated = await updateProject(project.id, { [field]: drafts[field] })
      setProject({ ...project, ...updated })
    } finally {
      setSaving(null)
    }
  }

  if (!project) return <p className="text-sm text-muted-foreground">Loading…</p>

  const latestTraffic = project.traffic_snapshots[0]

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">{project.name}</h1>
          <a href={project.url} target="_blank" rel="noreferrer" className="text-sm text-muted-foreground hover:underline">
            {project.url}
          </a>
        </div>
        {project.is_pipeline && <SeverityBadge severity={project.latest_alert_severity} />}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {EDITABLE_FIELDS.map(({ key, label }) => (
          <Card key={key}>
            <CardHeader>
              <CardTitle className="text-sm">{label}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <Label className="sr-only" htmlFor={key}>
                {label}
              </Label>
              <Textarea
                id={key}
                rows={4}
                value={drafts[key] ?? ''}
                disabled={isDemo}
                onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
              />
              {!isDemo && (
                <Button
                  size="sm"
                  className="self-end"
                  disabled={saving === key}
                  onClick={() => handleSave(key)}
                >
                  {saving === key ? 'Saving…' : 'Save'}
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {project.is_pipeline && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Backlog history</CardTitle>
          </CardHeader>
          <CardContent>
            <BacklogChart snapshots={project.pipeline_snapshots} />
          </CardContent>
        </Card>
      )}

      {project.is_pipeline && latestTraffic?.configured && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Search traffic (7d vs. prior 7d)</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-3 text-sm">
            {(['clicks', 'impressions', 'sessions'] as const).map((metric) => {
              const trend = latestTraffic[metric]
              if (!trend) return null
              return (
                <div key={metric}>
                  <p className="text-muted-foreground capitalize">{metric}</p>
                  <p className="text-lg font-semibold">{trend.recent}</p>
                  {trend.pct_change !== null && (
                    <p className={trend.pct_change < 0 ? 'text-destructive' : 'text-severity-green'}>
                      {trend.pct_change > 0 ? '+' : ''}
                      {trend.pct_change}%
                    </p>
                  )}
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Tasks</CardTitle>
        </CardHeader>
        <CardContent>
          <TaskBoard
            projectId={project.id}
            tasks={project.tasks}
            readOnly={isDemo}
            onChange={(tasks) => setProject({ ...project, tasks })}
          />
        </CardContent>
      </Card>
    </div>
  )
}
