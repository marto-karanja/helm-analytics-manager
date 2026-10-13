import * as React from 'react'
import { ArrowLeft } from 'lucide-react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { BacklogChart } from '@/components/BacklogChart'
import { IndexingSection } from '@/components/IndexingSection'
import { KeywordsSection } from '@/components/KeywordsSection'
import { RankingsSection } from '@/components/RankingsSection'
import { SitemapsSection } from '@/components/SitemapsSection'
import { TaskBoard } from '@/components/TaskBoard'
import { TrafficSection } from '@/components/TrafficSection'
import { TrendChip } from '@/components/TrendChip'
import { SeverityBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label, Textarea } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'
import { fetchProject, updateProject } from '@/lib/api'
import { formatNumber } from '@/lib/traffic'
import type { ProjectDetail } from '@/lib/types'

const EDITABLE_FIELDS = [
  { key: 'goals', label: 'Goals' },
  { key: 'current_status', label: 'Current status' },
  { key: 'blockers', label: 'Blockers' },
  { key: 'priority_notes', label: 'Priority notes' },
] as const

function Kpi({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
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

/** The numbers worth seeing before the tabs: search clicks, articles published, queue and open tasks. */
function ProjectKpis({ project }: { project: ProjectDetail }) {
  const pipeline = project.pipeline_snapshots[0]
  const clicks = project.traffic_snapshots[0]?.clicks ?? null
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" aria-label="Key numbers">
      <Kpi label="Clicks (7d)" value={clicks ? formatNumber(clicks.recent) : '—'}>
        <TrendChip pct={clicks?.pct_change} />
      </Kpi>
      <Kpi label="Published" value={formatNumber(pipeline?.total_articles_written)} />
      <Kpi label="In queue" value={formatNumber(pipeline?.backlog_count)} />
      <Kpi label="Open tasks" value={String(project.tasks.filter((t) => t.status !== 'done').length)} />
    </div>
  )
}

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'indexing', label: 'Indexing' },
  { key: 'rankings', label: 'Rankings' },
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

      {project.is_pipeline && <ProjectKpis project={project} />}

      {project.is_pipeline && (
        <nav className="sticky top-[57px] z-20 -mx-4 flex gap-1 overflow-x-auto border-b border-border bg-background/85 px-4 backdrop-blur-md" aria-label="Project sections">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              aria-current={tab === t.key ? 'page' : undefined}
              onClick={() => setSearchParams(t.key === 'overview' ? {} : { tab: t.key }, { replace: true })}
              className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                tab === t.key ? 'border-brand text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      )}

      {tab === 'indexing' && <IndexingSection projectId={project.id} isDemo={isDemo} />}
      {tab === 'rankings' && <RankingsSection projectId={project.id} isDemo={isDemo} />}
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
