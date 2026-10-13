import * as React from 'react'
import { useSearchParams } from 'react-router-dom'
import { Download } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { fetchProjects } from '@/lib/api'
import { downloadReportCsv, errorMessage, fetchCompare, fetchReport, fetchReportAvailability, fetchReportCatalog } from '@/lib/indexingApi'
import { formatDateTime, ISSUE_LABEL } from '@/lib/indexing'
import type { CompareData, IndexIssue, ReportAvailability, ReportCatalogItem, ReportCell, ReportData, ReportMeta, ReportQuery } from '@/lib/indexingTypes'
import type { Project } from '@/lib/types'
import { PageLoading } from '@/components/ui/skeleton'

const FALLBACK_REPORTS: ReportCatalogItem[] = [
  { name: 'indexing', label: 'Indexing', blurb: 'Counts of URLs per issue for each site.', kind: 'as_of', compare_keys: ['project'], history: '' },
  { name: 'non-indexed', label: 'Not indexed', blurb: 'Every URL with a problem.', kind: 'as_of', compare_keys: ['project', 'url'], history: '' },
  { name: 'striking-distance', label: 'Striking distance', blurb: 'Queries at positions 8 to 20.', kind: 'as_of', compare_keys: ['project', 'query'], history: '' },
  { name: 'digest', label: 'Weekly digest', blurb: 'One stored snapshot per site per week.', kind: 'as_of', compare_keys: ['project'], history: '' },
]

const COLUMN_LABEL: Record<string, string> = {
  clicks_change_pct: 'Clicks change %',
  impressions_change_pct: 'Impressions change %',
  indexed_percent: 'Indexed %',
  pending_keywords: 'Pending keywords',
  striking_distance: 'Striking distance',
  week_start: 'Week of',
  last_crawl_time: 'Last crawl',
  coverage_state: 'Coverage state',
  http_status: 'HTTP',
  total_urls: 'Total URLs',
  position_prior: 'Prior position',
  position_change: 'Position change',
  top_query: 'Top query',
  top_page: 'Top page',
  period_start: 'From',
  period_end: 'To',
  ctr: 'CTR',
  first_seen_at: 'First seen',
  recorded_at: 'Recorded',
  demand_source: 'Demand source',
  target_url: 'Target URL',
  created_at: 'Created',
  decided_at: 'Decided',
  change: 'Change',
}

const BASIS: Record<ReportMeta['basis'], { label: string; variant: 'green' | 'muted' | 'yellow' | 'red' }> = {
  current: { label: 'Current', variant: 'green' },
  stored: { label: 'Stored snapshot', variant: 'muted' },
  reconstructed: { label: 'Reconstructed', variant: 'yellow' },
  none: { label: 'No history', variant: 'red' },
}

// Compare rows and the summary chips: tinted, with a mark so colour is not the only cue.
const CHANGE_VARIANT: Record<string, 'green' | 'softred' | 'yellow' | 'muted'> = { new: 'green', gone: 'softred', changed: 'yellow', same: 'muted' }
const CHANGE_MARK: Record<string, string> = { new: '+', gone: '−', changed: '~', same: '=' }

const PERIODS = [7, 28, 90, 365]
const GRANULARITIES = [
  { value: 'total', label: 'One row per site' },
  { value: 'day', label: 'Daily' },
  { value: 'week', label: 'Weekly' },
  { value: 'month', label: 'Monthly' },
]

function baseLabel(column: string): string {
  if (COLUMN_LABEL[column]) return COLUMN_LABEL[column]
  if (column in ISSUE_LABEL) return ISSUE_LABEL[column as IndexIssue]
  const text = column.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function columnLabel(column: string, compare: boolean): string {
  if (compare) {
    if (column.endsWith('_delta')) return `Δ ${baseLabel(column.slice(0, -6))}`
    if (column.endsWith('_a') && column !== 'change') return `${baseLabel(column.slice(0, -2))} (A)`
    if (column.endsWith('_b')) return `${baseLabel(column.slice(0, -2))} (B)`
  }
  return baseLabel(column)
}

const DATETIME = /^\d{4}-\d{2}-\d{2}T/

function cell(value: ReportCell, column: string): string {
  if (value === null) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') {
    if (/(^|_)ctr(_a|_b|_delta)?$/.test(column)) return `${(value * 100).toFixed(2)}%`
    const text = value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    return column.endsWith('_delta') && value > 0 ? `+${text}` : text
  }
  return DATETIME.test(value) ? formatDateTime(value) : value
}

/** UTC calendar day `n` days before `from`, as YYYY-MM-DD. Reports are in UTC, so the picker is too. */
function isoDaysBefore(from: string, n: number): string {
  const d = new Date(`${from}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

function startOfMonth(from: string): string {
  return `${from.slice(0, 8)}01`
}

function clamp(day: string, first: string | null, last: string | null): string {
  if (first && day < first) return first
  if (last && day > last) return last
  return day
}

function BasisBadge({ meta, label }: { meta: ReportMeta; label?: string }) {
  const b = BASIS[meta.basis]
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      {label && <span className="text-muted-foreground">{label}</span>}
      <span className="font-medium">{meta.as_of}</span>
      <Badge variant={b.variant} title={meta.history}>
        {b.label}
      </Badge>
    </span>
  )
}

export function ReportsPage() {
  const [params, setParams] = useSearchParams()
  const [projects, setProjects] = React.useState<Project[]>([])
  const [catalog, setCatalog] = React.useState<ReportCatalogItem[]>(FALLBACK_REPORTS)
  const [availability, setAvailability] = React.useState<ReportAvailability | null>(null)
  const [report, setReport] = React.useState<ReportData | null>(null)
  const [compare, setCompare] = React.useState<CompareData | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [downloading, setDownloading] = React.useState(false)

  const name = params.get('report') ?? 'indexing'
  const project = params.get('project') ?? ''
  const asOf = params.get('date') ?? ''
  const compareWith = params.get('compare') ?? ''
  const days = Number(params.get('days')) || 28
  const granularity = params.get('granularity') ?? 'total'
  const changedOnly = params.get('changed') === '1'
  const isCompare = compareWith !== ''

  const spec = catalog.find((r) => r.name === name) ?? catalog[0]
  const range = availability?.reports[spec.name]
  const today = availability?.today ?? new Date().toISOString().slice(0, 10)
  const first = range?.from ?? null
  const last = range?.to ?? today
  const mainDate = asOf || last

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setParams(next, { replace: true })
  }

  React.useEffect(() => {
    fetchProjects()
      .then((all) => setProjects(all.filter((p) => p.is_pipeline)))
      .catch(() => undefined)
    fetchReportCatalog()
      .then(setCatalog)
      .catch(() => undefined)
  }, [])

  React.useEffect(() => {
    fetchReportAvailability(project || undefined)
      .then(setAvailability)
      .catch(() => setAvailability(null))
  }, [project])

  const query = React.useMemo<ReportQuery>(() => {
    const q: ReportQuery = { project: project || undefined }
    if (spec.kind === 'range') {
      q.days = days
      q.granularity = granularity
    }
    if (isCompare) {
      q.a = compareWith
      q.b = mainDate
      q.changed_only = changedOnly
    } else if (asOf || spec.kind === 'range') {
      // A period report defaults to the newest day with data (shown in the date box), not to today.
      q.as_of = asOf || mainDate
    }
    return q
  }, [project, spec.kind, days, granularity, isCompare, compareWith, mainDate, changedOnly, asOf])

  React.useEffect(() => {
    let cancelled = false
    setReport(null)
    setCompare(null)
    setError(null)
    const request = isCompare
      ? fetchCompare(spec.name, query).then((r) => !cancelled && setCompare(r))
      : fetchReport(spec.name, query).then((r) => !cancelled && setReport(r))
    request.catch((err) => !cancelled && setError(errorMessage(err, 'Failed to load the report.')))
    return () => {
      cancelled = true
    }
  }, [spec.name, query, isCompare])

  async function download() {
    setDownloading(true)
    try {
      await downloadReportCsv(spec.name, query, isCompare)
    } catch (err) {
      setError(errorMessage(err, 'Download failed.'))
    } finally {
      setDownloading(false)
    }
  }

  function pickReport(next: string) {
    // A date that one report cannot answer is dropped rather than carried to a report that has no history for it.
    update({ report: next === 'indexing' ? null : next, date: null, compare: null, changed: null })
  }

  function quickDate(n: number | 'month') {
    const target = n === 'month' ? startOfMonth(last) : isoDaysBefore(last, n)
    update({ date: target === last ? null : clamp(target, first, last) })
  }

  function startCompare() {
    update({ compare: clamp(isoDaysBefore(mainDate, spec.kind === 'range' ? days : 7), first, last) })
  }

  const data = isCompare ? compare : report
  const metas = isCompare ? (compare ? [compare.meta.a, compare.meta.b] : []) : report ? [report.meta] : []
  // Both dates often carry the same note (e.g. "Reconstructed ..."), so show each distinct note once.
  const notes = Array.from(new Set(isCompare ? (compare?.meta.notes ?? []) : report?.meta.note ? [report.meta.note] : []))
  const empty = data !== null && data.rows.length === 0
  const outOfRange = metas.some((m) => m.out_of_range)

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Reports</h1>

      <div className="sticky top-[57px] z-20 -mx-4 flex flex-wrap items-center justify-between gap-2 bg-background/85 px-4 py-2 backdrop-blur-md">
        <SegmentedControl
          label="Report"
          options={catalog.map((r) => ({ value: r.name, label: r.label }))}
          value={spec.name}
          onChange={pickReport}
        />
        <div className="flex items-center gap-2">
          <Select className="w-auto" aria-label="Project" value={project} onChange={(e) => update({ project: e.target.value, date: null, compare: null })}>
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.slug}>
                {p.name}
              </option>
            ))}
          </Select>
          <Button size="sm" variant="outline" disabled={downloading || !data} onClick={download}>
            <Download size={14} /> CSV
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">{spec.blurb}</p>

      <Card>
        <CardContent className="flex flex-col gap-3 p-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {spec.kind === 'range' ? 'Period ends on' : 'Report date'} (UTC)
              <Input
                type="date"
                className="w-40"
                aria-label="Report date"
                min={first ?? undefined}
                max={last}
                value={mainDate}
                onChange={(e) => update({ date: e.target.value && e.target.value !== last ? e.target.value : null })}
              />
            </label>
            <div className="flex flex-wrap gap-1" role="group" aria-label="Quick dates">
              <Button size="sm" variant="outline" onClick={() => update({ date: null })}>
                Today
              </Button>
              <Button size="sm" variant="outline" onClick={() => quickDate(7)}>
                1 week ago
              </Button>
              <Button size="sm" variant="outline" onClick={() => quickDate(30)}>
                1 month ago
              </Button>
              <Button size="sm" variant="outline" onClick={() => quickDate('month')}>
                Start of month
              </Button>
            </div>

            {spec.kind === 'range' && (
              <>
                <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                  Period
                  <Select className="w-32" aria-label="Period" value={String(days)} onChange={(e) => update({ days: e.target.value === '28' ? null : e.target.value })}>
                    {PERIODS.map((d) => (
                      <option key={d} value={d}>
                        Last {d} days
                      </option>
                    ))}
                  </Select>
                </label>
                {!isCompare && (
                  <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                    Rows
                    <Select className="w-40" aria-label="Rows" value={granularity} onChange={(e) => update({ granularity: e.target.value === 'total' ? null : e.target.value })}>
                      {GRANULARITIES.map((g) => (
                        <option key={g.value} value={g.value}>
                          {g.label}
                        </option>
                      ))}
                    </Select>
                  </label>
                )}
              </>
            )}

            <div className="ml-auto flex items-end gap-2">
              {isCompare ? (
                <Button size="sm" variant="outline" onClick={() => update({ compare: null, changed: null })}>
                  Stop comparing
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={startCompare}>
                  Compare with another date
                </Button>
              )}
            </div>
          </div>

          {isCompare && (
            <div className="flex flex-wrap items-end gap-3 border-t border-border pt-3">
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                Compare against (A)
                <Input
                  type="date"
                  className="w-40"
                  aria-label="Compare date"
                  min={first ?? undefined}
                  max={last}
                  value={compareWith}
                  onChange={(e) => update({ compare: e.target.value || null })}
                />
              </label>
              <span className="pb-2 text-xs text-muted-foreground">
                A is compared with B, the report date above. {spec.kind === 'range' ? `Each date ends a period of ${days} days. ` : ''}
                Rows are marked new (only in B), gone (only in A), changed or same.
              </span>
              <label className="ml-auto flex items-center gap-2 pb-2 text-sm">
                <input type="checkbox" checked={changedOnly} onChange={(e) => update({ changed: e.target.checked ? '1' : null })} />
                Changed rows only
              </label>
            </div>
          )}

          {range && (
            <p className="text-xs text-muted-foreground">
              {first ? `This report has history from ${first}.` : 'Nothing has been collected for this report yet.'} {range.history}
            </p>
          )}
        </CardContent>
      </Card>

      {metas.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1" data-testid="report-basis">
          {isCompare ? (
            <>
              <BasisBadge meta={metas[0]} label="A" />
              <BasisBadge meta={metas[1]} label="B" />
            </>
          ) : (
            <BasisBadge meta={metas[0]} label="As of" />
          )}
          {compare && (
            <span className="flex gap-1 text-xs" data-testid="compare-summary">
              {(['new', 'gone', 'changed', 'same'] as const).map((s) => (
                <Badge key={s} variant={CHANGE_VARIANT[s]}>
                  <span aria-hidden>{CHANGE_MARK[s]}</span>
                  {compare.summary[s]} {s}
                </Badge>
              ))}
            </span>
          )}
        </div>
      )}
      {notes.map((n) => (
        <p key={n} className={`text-sm ${outOfRange ? 'font-medium' : 'text-muted-foreground'}`} role="note">
          {n}
        </p>
      ))}

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!data && !error && <PageLoading />}

      {data && !(empty && outOfRange) && (
        <div className="max-h-[70vh] overflow-auto rounded-md border border-border" tabIndex={0}>
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card text-left text-muted-foreground">
              <tr>
                {data.columns.map((c) => (
                  <th key={c} className="px-3 py-2 font-medium whitespace-nowrap">
                    {columnLabel(c, isCompare)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i} className="border-t border-border">
                  {row.map((value, j) => {
                    const column = data.columns[j]
                    if (isCompare && column === 'change') {
                      return (
                        <td key={j} className="px-3 py-1.5">
                          <Badge variant={CHANGE_VARIANT[String(value)] ?? 'outline'}>
                            <span aria-hidden>{CHANGE_MARK[String(value)] ?? ''}</span>
                            {String(value)}
                          </Badge>
                        </td>
                      )
                    }
                    return (
                      <td key={j} className="max-w-sm truncate px-3 py-1.5" title={typeof value === 'string' ? value : undefined}>
                        {cell(value, column)}
                      </td>
                    )
                  })}
                </tr>
              ))}
              {empty && (
                <tr>
                  <td colSpan={data.columns.length} className="px-3 py-6 text-center text-muted-foreground">
                    {isCompare ? 'No rows to compare.' : 'Nothing to report for this date.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {data && data.rows.length > 0 && (
        <Card>
          <CardContent className="p-3 text-xs text-muted-foreground">{data.rows.length} row(s). The CSV matches this table.</CardContent>
        </Card>
      )}
    </div>
  )
}
