import * as React from 'react'
import { Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select } from '@/components/ui/input'
import { fetchProjects } from '@/lib/api'
import { downloadReportCsv, errorMessage, fetchReport } from '@/lib/indexingApi'
import { ISSUE_LABEL } from '@/lib/indexing'
import type { IndexIssue, ReportData } from '@/lib/indexingTypes'
import type { Project } from '@/lib/types'

const REPORTS = [
  { name: 'indexing', label: 'Indexing', blurb: 'Counts of URLs per issue for each site.' },
  { name: 'non-indexed', label: 'Not indexed', blurb: 'Every URL with a problem: issue, last crawl, word count.' },
  { name: 'striking-distance', label: 'Striking distance', blurb: 'Queries at positions 8 to 20 that are worth a push.' },
  { name: 'digest', label: 'Weekly digest', blurb: 'One stored snapshot per site per week.' },
] as const

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
}

function columnLabel(column: string): string {
  if (COLUMN_LABEL[column]) return COLUMN_LABEL[column]
  if (column in ISSUE_LABEL) return ISSUE_LABEL[column as IndexIssue]
  const text = column.replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

function cell(value: ReportData['rows'][number][number]): string {
  if (value === null) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') return value.toLocaleString()
  return value
}

export function ReportsPage() {
  const [projects, setProjects] = React.useState<Project[]>([])
  const [project, setProject] = React.useState('')
  const [name, setName] = React.useState<(typeof REPORTS)[number]['name']>('indexing')
  const [report, setReport] = React.useState<ReportData | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [downloading, setDownloading] = React.useState(false)

  React.useEffect(() => {
    fetchProjects()
      .then((all) => setProjects(all.filter((p) => p.is_pipeline)))
      .catch(() => undefined)
  }, [])

  React.useEffect(() => {
    let cancelled = false
    setReport(null)
    setError(null)
    fetchReport(name, project || undefined)
      .then((r) => !cancelled && setReport(r))
      .catch((err) => !cancelled && setError(errorMessage(err, 'Failed to load the report.')))
    return () => {
      cancelled = true
    }
  }, [name, project])

  async function download() {
    setDownloading(true)
    try {
      await downloadReportCsv(name, project || undefined)
    } catch (err) {
      setError(errorMessage(err, 'Download failed.'))
    } finally {
      setDownloading(false)
    }
  }

  const current = REPORTS.find((r) => r.name === name)!

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Reports</h1>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Report">
          {REPORTS.map((r) => (
            <Button key={r.name} size="sm" variant={name === r.name ? 'default' : 'outline'} aria-pressed={name === r.name} onClick={() => setName(r.name)}>
              {r.label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Select className="w-auto" aria-label="Project" value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.slug}>
                {p.name}
              </option>
            ))}
          </Select>
          <Button size="sm" variant="outline" disabled={downloading || !report} onClick={download}>
            <Download size={14} /> CSV
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">{current.blurb}</p>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {!report && !error && <p className="text-sm text-muted-foreground">Loading…</p>}

      {report && (
        <div className="max-h-[70vh] overflow-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card text-left text-muted-foreground">
              <tr>
                {report.columns.map((c) => (
                  <th key={c} className="px-3 py-2 font-medium whitespace-nowrap">
                    {columnLabel(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {report.rows.map((row, i) => (
                <tr key={i} className="border-t border-border">
                  {row.map((value, j) => (
                    <td key={j} className="max-w-sm truncate px-3 py-1.5" title={typeof value === 'string' ? value : undefined}>
                      {cell(value)}
                    </td>
                  ))}
                </tr>
              ))}
              {report.rows.length === 0 && (
                <tr>
                  <td colSpan={report.columns.length} className="px-3 py-6 text-center text-muted-foreground">
                    Nothing to report yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {report && report.rows.length > 0 && (
        <Card>
          <CardContent className="p-3 text-xs text-muted-foreground">{report.rows.length} row(s). The CSV matches this table.</CardContent>
        </Card>
      )}
    </div>
  )
}
