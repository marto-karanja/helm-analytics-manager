import * as React from 'react'
import { ArrowLeft } from 'lucide-react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { BacklogChart } from '@/components/BacklogChart'
import { IndexingSection } from '@/components/IndexingSection'
import { KeywordsSection } from '@/components/KeywordsSection'
import { SitemapsSection } from '@/components/SitemapsSection'
import { TaskBoard } from '@/components/TaskBoard'
import { TrafficSection } from '@/components/TrafficSection'
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

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'indexing', label: 'Indexing' },
  { key: 'keywords', label: 'Keywords' },
  { key: 'sitemaps', label: 'Sitemaps' },
] as const
type TabKey = (typeof TABS)[number]['key']

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const requestedKey: TabKey = TABS.some((t) => t.key === requestedTab) ? (requestedTab as TabKey) : 'overview'
  const [project, setProject] = React.useState<ProjectDetail | null>(null)
  const [drafts, setDrafts] = React.useState<Record<string, string>>({})
  const [saving, setSaving] = React.useState<string | null>(null)
  const { isDemo } = useAuth()
  const { hash } = useLocation()

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

  // Deep links like /projects/:id#traffic (from the Traffic page) can only scroll once the section has rendered.
  React.useEffect(() => {
    if (project && hash) document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [project, hash])

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
  const tab: TabKey = project.is_pipeline ? requestedKey : 'overview'

  return (
    <div className="flex flex-col gap-6">
      <Link to="/" className="flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft size={14} /> Overview
      </Link>
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">{project.name}</h1>
          <a href={project.url} target="_blank" rel="noreferrer" className="text-sm text-muted-foreground hover:underline">
            {project.url}
          </a>
        </div>
        {project.is_pipeline && <SeverityBadge severity={project.latest_alert_severity} />}
      </div>

      {project.is_pipeline && (
        <nav className="flex gap-1 border-b border-border" aria-label="Project sections">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              aria-current={tab === t.key ? 'page' : undefined}
              onClick={() => setSearchParams(t.key === 'overview' ? {} : { tab: t.key }, { replace: true })}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                tab === t.key ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      )}

      {tab === 'indexing' && <IndexingSection projectId={project.id} isDemo={isDemo} />}
      {tab === 'keywords' && <KeywordsSection projectId={project.id} isDemo={isDemo} />}
      {tab === 'sitemaps' && <SitemapsSection projectId={project.id} />}

      {tab === 'overview' && (<>
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

      {project.is_pipeline && <TrafficSection project={project} isDemo={isDemo} />}

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
      </>)}
    </div>
  )
}
