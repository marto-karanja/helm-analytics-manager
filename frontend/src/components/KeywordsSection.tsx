import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime, shortPath } from '@/lib/indexing'
import {
  bulkSetStatus,
  errorMessage,
  exportKeywordQueue,
  fetchKeywords,
  setCandidateStatus,
  startKeywordRun,
} from '@/lib/indexingApi'
import type { CandidateStatus, DecidableStatus, KeywordCandidate, KeywordList, KeywordRun } from '@/lib/indexingTypes'
import { formatNumber } from '@/lib/traffic'

const FILTERS: { value: CandidateStatus | 'all'; label: string }[] = [
  { value: 'proposed', label: 'Proposed' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'written', label: 'Exported' },
  { value: 'all', label: 'All' },
]
const SOURCE_LABEL: Record<KeywordCandidate['demand_source'], string> = {
  gsc: 'Search Console',
  kp_exact: 'Keyword Planner',
  kp_bucket: 'Keyword Planner (range)',
  none: 'No data',
}
const GAP_LABEL: Record<string, string> = {
  striking_distance: 'Striking distance',
  no_page: 'No page yet',
  ranking: 'Already ranking',
  other: 'Page exists',
}
const POLL_MS = 3000

function volumeText(c: KeywordCandidate): string {
  if (c.volume !== null) return `${c.volume_is_bucket ? '~' : ''}${formatNumber(c.volume)}`
  // No Keyword Planner figure: show the estimate Search Console impressions imply, marked as an estimate.
  if (c.demand_source === 'gsc' && c.demand_est !== null) return `est. ${formatNumber(Math.round(c.demand_est))}`
  return 'n/a'
}

function RunPanel({
  run,
  llmConfigured,
  canRun,
  starting,
  onStart,
  message,
}: {
  run: KeywordRun | undefined
  llmConfigured: boolean
  canRun: boolean
  starting: boolean
  onStart: () => void
  message: string | null
}) {
  const running = run?.status === 'running'
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>Keyword generator</span>
          {canRun && (
            <Button size="sm" disabled={!llmConfigured || running || starting} onClick={onStart}>
              {running || starting ? 'Running…' : 'Run generator'}
            </Button>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 text-sm text-muted-foreground">
        {!llmConfigured && canRun && <p>HELM_ANTHROPIC_API_KEY is not set on the server, so the generator is off.</p>}
        {message && <p className="text-destructive">{message}</p>}
        {!run ? (
          <p>No runs yet. A run reads Search Console queries and page titles, asks Claude for new keyword clusters, then scores everything.</p>
        ) : (
          <>
            <p className="flex flex-wrap items-center gap-2">
              <Badge variant={run.status === 'ok' ? 'green' : run.status === 'error' ? 'red' : 'yellow'}>{run.status}</Badge>
              <span>Started {formatDateTime(run.started_at)}</span>
              {run.finished_at && <span>· finished {formatDateTime(run.finished_at)}</span>}
              {run.cost_usd !== null && <span>· ${run.cost_usd.toFixed(3)}</span>}
              {run.model && <span>· {run.model}</span>}
            </p>
            {run.source_counts && (
              <p>
                Seeds: {Object.entries(run.source_counts).map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}
              </p>
            )}
            {run.error && <p className="text-destructive">{run.error}</p>}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function KeywordsSection({ projectId, isDemo }: { projectId: string; isDemo: boolean }) {
  const [data, setData] = React.useState<KeywordList | null>(null)
  const [filter, setFilter] = React.useState<CandidateStatus | 'all'>('proposed')
  const [selected, setSelected] = React.useState<Set<string>>(new Set())
  const [error, setError] = React.useState<string | null>(null)
  const [notice, setNotice] = React.useState<string | null>(null)
  const [runMessage, setRunMessage] = React.useState<string | null>(null)
  const [starting, setStarting] = React.useState(false)
  const [reload, setReload] = React.useState(0)

  const load = React.useCallback(
    () =>
      fetchKeywords(projectId, filter === 'all' ? undefined : filter)
        .then(setData)
        .catch(() => setError('Failed to load keywords.')),
    [projectId, filter],
  )

  React.useEffect(() => {
    load()
  }, [load, reload])

  // While a run is going, poll so the status panel and the table fill in without a manual refresh.
  const running = data?.runs[0]?.status === 'running'
  React.useEffect(() => {
    if (!running) return
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [running, load])

  async function startRun() {
    setStarting(true)
    setRunMessage(null)
    try {
      await startKeywordRun(projectId)
      setReload((n) => n + 1)
    } catch (err) {
      setRunMessage(errorMessage(err, 'Could not start a run.'))
    } finally {
      setStarting(false)
    }
  }

  async function decide(ids: string[], status: DecidableStatus) {
    setNotice(null)
    try {
      if (ids.length === 1) await setCandidateStatus(ids[0], status)
      else await bulkSetStatus(projectId, ids, status)
      setSelected(new Set())
      setReload((n) => n + 1)
    } catch (err) {
      setNotice(errorMessage(err, 'Could not update the keywords.'))
    }
  }

  async function exportQueue() {
    setNotice(null)
    try {
      const result = await exportKeywordQueue(projectId)
      setNotice(
        result.path
          ? `Exported ${result.count} keyword(s) to the queue file.`
          : `Marked ${result.count} keyword(s) as exported. File export is not configured on the server; pipelines can pull the queue with an MCP token.`,
      )
      setReload((n) => n + 1)
    } catch (err) {
      setNotice(errorMessage(err, 'Export failed.'))
    }
  }

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>

  const rows = data.candidates
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id))
  const canEdit = !isDemo

  return (
    <div className="flex flex-col gap-4">
      <RunPanel
        run={data.runs[0]}
        llmConfigured={data.llm_configured}
        canRun={canEdit}
        starting={starting}
        onStart={startRun}
        message={runMessage}
      />

      <p className="text-xs text-muted-foreground">
        Demand comes from {data.volume_source === 'keyword_planner' ? 'Keyword Planner where available, then Search Console impressions' : 'Search Console impressions'}.
        "n/a" means no volume data; "~" marks a Keyword Planner range, not an exact figure. Nothing is published automatically.
      </p>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Status filter">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={filter === f.value ? 'default' : 'outline'}
              aria-pressed={filter === f.value}
              onClick={() => {
                setFilter(f.value)
                setSelected(new Set())
              }}
            >
              {f.label}
              {f.value !== 'all' && ` (${data.counts[f.value]})`}
            </Button>
          ))}
        </div>
        {canEdit && (
          <div className="flex flex-wrap gap-1">
            <Button size="sm" disabled={selected.size === 0} onClick={() => decide([...selected], 'accepted')}>
              Accept selected
            </Button>
            <Button size="sm" variant="outline" disabled={selected.size === 0} onClick={() => decide([...selected], 'rejected')}>
              Reject selected
            </Button>
            <Button size="sm" variant="outline" disabled={data.counts.accepted === 0} onClick={exportQueue}>
              Export queue ({data.counts.accepted})
            </Button>
          </div>
        )}
      </div>
      {notice && <p className="text-sm text-muted-foreground">{notice}</p>}

      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-card text-left text-muted-foreground">
            <tr>
              {canEdit && (
                <th className="w-8 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))}
                  />
                </th>
              )}
              {['Keyword', 'Intent', 'Volume', 'Impressions', 'Gap', 'Score', 'Target', 'Status', ...(canEdit ? [''] : [])].map((h, i) => (
                <th key={`${h}-${i}`} className="px-3 py-2 font-medium whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t border-border align-top">
                {canEdit && (
                  <td className="px-3 py-1.5">
                    <input
                      type="checkbox"
                      aria-label={`Select ${c.keyword}`}
                      disabled={c.status === 'written'}
                      checked={selected.has(c.id)}
                      onChange={() => {
                        const next = new Set(selected)
                        if (next.has(c.id)) next.delete(c.id)
                        else next.add(c.id)
                        setSelected(next)
                      }}
                    />
                  </td>
                )}
                <td className="px-3 py-1.5">
                  <p className="font-medium">{c.keyword}</p>
                  {c.cluster_label && <p className="max-w-xs truncate text-xs text-muted-foreground">{c.cluster_label}</p>}
                </td>
                <td className="px-3 py-1.5">{c.intent ?? '—'}</td>
                <td className="px-3 py-1.5 whitespace-nowrap" title={SOURCE_LABEL[c.demand_source]}>
                  {volumeText(c)}
                  <p className="text-xs text-muted-foreground">{SOURCE_LABEL[c.demand_source]}</p>
                </td>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  {c.impressions_proxy === null ? '—' : formatNumber(c.impressions_proxy)}
                  {c.position_avg !== null && <p className="text-xs text-muted-foreground">pos {c.position_avg.toFixed(1)}</p>}
                </td>
                <td className="px-3 py-1.5">
                  {c.gap ? <Badge variant={c.gap === 'striking_distance' ? 'green' : 'muted'}>{GAP_LABEL[c.gap] ?? c.gap}</Badge> : '—'}
                </td>
                <td className="px-3 py-1.5 font-medium">{c.score.toFixed(1)}</td>
                <td className="max-w-48 px-3 py-1.5">
                  {c.target_url ? (
                    <a href={c.target_url} target="_blank" rel="noreferrer" className="block truncate hover:underline" title={c.target_url}>
                      Improve {shortPath(c.target_url)}
                    </a>
                  ) : (
                    <span className="text-muted-foreground">New article</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  <Badge variant={c.status === 'accepted' ? 'green' : c.status === 'rejected' ? 'muted' : c.status === 'written' ? 'outline' : 'yellow'}>
                    {c.status === 'written' ? 'exported' : c.status}
                  </Badge>
                </td>
                {canEdit && (
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    {c.status !== 'written' && (
                      <div className="flex gap-1">
                        {c.status !== 'accepted' && (
                          <Button size="sm" variant="outline" onClick={() => decide([c.id], 'accepted')}>
                            Accept
                          </Button>
                        )}
                        {c.status !== 'rejected' && (
                          <Button size="sm" variant="ghost" onClick={() => decide([c.id], 'rejected')}>
                            Reject
                          </Button>
                        )}
                        {c.status !== 'proposed' && (
                          <Button size="sm" variant="ghost" onClick={() => decide([c.id], 'proposed')}>
                            Reopen
                          </Button>
                        )}
                      </div>
                    )}
                  </td>
                )}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={canEdit ? 10 : 8} className="px-3 py-6 text-center text-muted-foreground">
                  No keywords here yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
