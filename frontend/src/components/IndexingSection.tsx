import * as React from 'react'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import {
  errorMessage,
  fetchIndexedUrls,
  fetchIndexingSummary,
  fetchUrlDetail,
  inspectUrlNow,
} from '@/lib/indexingApi'
import { formatDate, formatDateTime, ISSUE_HINT, ISSUE_LABEL, ISSUE_ORDER, issueVariant, shortPath } from '@/lib/indexing'
import type { IndexedUrl, IndexIssue, IndexingSummary, UrlDetail } from '@/lib/indexingTypes'
import { formatNumber } from '@/lib/traffic'

const PAGE_SIZE = 50
const TOOLTIP_STYLE = {
  background: 'var(--color-card)',
  border: '1px solid var(--color-border)',
  borderRadius: 6,
  fontSize: 12,
}

function IssueBadge({ issue }: { issue: IndexIssue }) {
  return <Badge variant={issueVariant(issue)}>{ISSUE_LABEL[issue]}</Badge>
}

function IndexedTrend({ history }: { history: IndexingSummary['history'] }) {
  const data = history.map((h) => ({ date: h.date, indexed: h.counts.indexed ?? 0 }))
  if (data.length < 2) {
    return <p className="text-xs text-muted-foreground">The trend appears after the second daily snapshot.</p>
  }
  return (
    <ResponsiveContainer width="100%" height={70}>
      <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
        <XAxis dataKey="date" hide />
        <YAxis hide domain={['auto', 'auto']} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={{ color: 'var(--color-card-foreground)' }}
          itemStyle={{ color: 'var(--color-card-foreground)' }}
          formatter={(v) => [String(v), 'Indexed URLs']}
        />
        <Line type="monotone" dataKey="indexed" stroke="var(--color-primary)" strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function UrlDrawer({
  projectId,
  url,
  canInspect,
  hasSearchConsole,
  onClose,
  onInspected,
}: {
  projectId: string
  url: IndexedUrl
  canInspect: boolean
  hasSearchConsole: boolean
  onClose: () => void
  onInspected: () => void
}) {
  const [detail, setDetail] = React.useState<UrlDetail | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [message, setMessage] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  React.useEffect(() => {
    let cancelled = false
    setDetail(null)
    setError(null)
    fetchUrlDetail(projectId, url.id)
      .then((d) => !cancelled && setDetail(d))
      .catch(() => !cancelled && setError('Failed to load this URL.'))
    return () => {
      cancelled = true
    }
  }, [projectId, url.id])

  async function inspect() {
    setBusy(true)
    setMessage(null)
    try {
      const result = await inspectUrlNow(projectId, url.url)
      setMessage(`Queued. The collector runs it within about a minute. ${result.budget.remaining} inspections left today.`)
      onInspected()
    } catch (err) {
      setMessage(errorMessage(err, 'Could not queue the inspection.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose} role="presentation">
      <aside
        className="flex h-full w-full max-w-lg flex-col gap-4 overflow-y-auto border-l border-border bg-background p-4"
        onClick={(e) => e.stopPropagation()}
        aria-label="URL details"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <a href={url.url} target="_blank" rel="noreferrer" className="break-all text-sm font-medium hover:underline">
              {url.url}
            </a>
            <div className="mt-1 flex items-center gap-2">
              <IssueBadge issue={detail?.issue ?? url.issue} />
              <span className="text-xs text-muted-foreground">{ISSUE_HINT[detail?.issue ?? url.issue]}</span>
            </div>
          </div>
          <Button variant="ghost" size="sm" aria-label="Close" onClick={onClose}>
            <X size={16} />
          </Button>
        </div>

        {canInspect && (
          <div className="flex flex-col gap-1">
            <Button size="sm" className="self-start" disabled={busy || !hasSearchConsole} onClick={inspect}>
              {busy ? 'Queuing…' : 'Inspect now'}
            </Button>
            {!hasSearchConsole && <p className="text-xs text-muted-foreground">This project has no Search Console property.</p>}
            {message && <p className="text-xs text-muted-foreground">{message}</p>}
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
        {!detail && !error && <p className="text-sm text-muted-foreground">Loading…</p>}

        {detail && (
          <>
            <section>
              <h3 className="mb-2 text-sm font-semibold">Latest page signals</h3>
              {detail.signals.length === 0 ? (
                <p className="text-sm text-muted-foreground">Not fetched yet.</p>
              ) : (
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                  {(() => {
                    const s = detail.signals[0]
                    return (
                      <>
                        <dt className="text-muted-foreground">Fetched</dt>
                        <dd>{formatDateTime(s.fetched_at)} ({s.source})</dd>
                        <dt className="text-muted-foreground">HTTP status</dt>
                        <dd>{s.http_status ?? s.error ?? '—'}</dd>
                        <dt className="text-muted-foreground">Title</dt>
                        <dd>{s.title ?? '—'}</dd>
                        <dt className="text-muted-foreground">Words</dt>
                        <dd>{formatNumber(s.word_count)}</dd>
                        <dt className="text-muted-foreground">H1 / H2</dt>
                        <dd>{s.h1_count ?? '—'} / {s.h2_count ?? '—'}</dd>
                        <dt className="text-muted-foreground">Internal links</dt>
                        <dd>{formatNumber(s.internal_links)}</dd>
                        <dt className="text-muted-foreground">Canonical</dt>
                        <dd className="break-all">{s.canonical ?? '—'}</dd>
                        <dt className="text-muted-foreground">noindex</dt>
                        <dd>{s.noindex ? 'yes' : 'no'}</dd>
                      </>
                    )
                  })()}
                </dl>
              )}
            </section>

            <section>
              <h3 className="mb-2 text-sm font-semibold">Inspection history</h3>
              {detail.inspections.length === 0 ? (
                <p className="text-sm text-muted-foreground">Never inspected.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {detail.inspections.map((i) => (
                    <li key={i.inspected_at} className="rounded-md border border-border p-2 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{i.coverage_state ?? i.verdict ?? 'No result'}</span>
                        <span className="text-xs text-muted-foreground">{formatDateTime(i.inspected_at)}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Verdict {i.verdict ?? '—'} · fetch {i.page_fetch_state ?? '—'} · robots {i.robots_txt_state ?? '—'} · last crawl{' '}
                        {formatDate(i.last_crawl_time)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </aside>
    </div>
  )
}

export function IndexingSection({ projectId, isDemo }: { projectId: string; isDemo: boolean }) {
  const [summary, setSummary] = React.useState<IndexingSummary | null>(null)
  const [list, setList] = React.useState<{ total: number; items: IndexedUrl[] } | null>(null)
  const [issue, setIssue] = React.useState<IndexIssue | ''>('')
  const [query, setQuery] = React.useState('')
  const [search, setSearch] = React.useState('')
  const [page, setPage] = React.useState(0)
  const [selected, setSelected] = React.useState<IndexedUrl | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [reload, setReload] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    fetchIndexingSummary(projectId)
      .then((s) => !cancelled && setSummary(s))
      .catch(() => !cancelled && setError('Failed to load indexing data.'))
    return () => {
      cancelled = true
    }
  }, [projectId, reload])

  // Typing in the search box should not fire a request per keystroke.
  React.useEffect(() => {
    const id = setTimeout(() => {
      setSearch(query)
      setPage(0)
    }, 300)
    return () => clearTimeout(id)
  }, [query])

  React.useEffect(() => {
    let cancelled = false
    fetchIndexedUrls(projectId, { issue: issue || undefined, q: search || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE })
      .then((l) => !cancelled && setList(l))
      .catch(() => !cancelled && setError('Failed to load URLs.'))
    return () => {
      cancelled = true
    }
  }, [projectId, issue, search, page, reload])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!summary) return <p className="text-sm text-muted-foreground">Loading…</p>

  if (summary.total === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          No sitemap URLs yet. The collector walks the sitemap daily; once it has, every URL appears here with its indexing status.
        </CardContent>
      </Card>
    )
  }

  const pages = list ? Math.max(1, Math.ceil(list.total / PAGE_SIZE)) : 1
  const tiles = ISSUE_ORDER.filter((i) => i !== 'unknown' || summary.counts.unknown > 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {tiles.map((i) => (
          <button
            key={i}
            type="button"
            aria-pressed={issue === i}
            title={ISSUE_HINT[i]}
            onClick={() => {
              setIssue(issue === i ? '' : i)
              setPage(0)
            }}
            className={`rounded-lg border p-3 text-left transition-colors hover:bg-accent ${issue === i ? 'border-primary bg-accent' : 'border-border bg-card'}`}
          >
            <p className="text-xs text-muted-foreground">{ISSUE_LABEL[i]}</p>
            <p className="text-2xl font-semibold">{formatNumber(summary.counts[i])}</p>
          </button>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span>
              {summary.indexed_percent === null ? 'Indexed share unknown' : `${summary.indexed_percent}% of checked URLs indexed`}
            </span>
            <span className="text-xs font-normal text-muted-foreground">
              Sitemap walked {formatDateTime(summary.last_sitemap_walk_at)} · last inspection {formatDateTime(summary.last_inspection_at)}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <IndexedTrend history={summary.history} />
          <p className="text-xs text-muted-foreground">
            Inspection budget today: {summary.budget.spent_today} used of {summary.budget.budget}
            {summary.budget.queued > 0 && `, ${summary.budget.queued} queued`}. Thin means under {summary.thin_word_threshold} words.
            {!summary.has_search_console && ' No Search Console property: page signals only, no Google index status.'}
          </p>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          className="w-auto"
          aria-label="Filter by issue"
          value={issue}
          onChange={(e) => {
            setIssue(e.target.value as IndexIssue | '')
            setPage(0)
          }}
        >
          <option value="">All issues</option>
          {ISSUE_ORDER.map((i) => (
            <option key={i} value={i}>
              {ISSUE_LABEL[i]}
            </option>
          ))}
        </Select>
        <Input className="max-w-xs" placeholder="Search URL or title" aria-label="Search URLs" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="text-xs text-muted-foreground">{list ? `${formatNumber(list.total)} URLs` : ''}</span>
      </div>

      <div className="overflow-x-auto rounded-md border border-border" tabIndex={0}>
        <table className="w-full text-sm">
          <thead className="bg-card text-left text-muted-foreground">
            <tr>
              {['URL', 'Status', 'Coverage state', 'Last crawl', 'Words', 'HTTP'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list?.items.map((row) => (
              <tr key={row.id} className="cursor-pointer border-t border-border hover:bg-accent" onClick={() => setSelected(row)}>
                <td className="max-w-xs px-3 py-1.5">
                  <button type="button" className="block max-w-full truncate text-left hover:underline" title={row.url} onClick={() => setSelected(row)}>
                    {shortPath(row.url)}
                  </button>
                  {row.title && <p className="truncate text-xs text-muted-foreground">{row.title}</p>}
                </td>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  <IssueBadge issue={row.issue} />
                </td>
                <td className="px-3 py-1.5">{row.coverage_state ?? '—'}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{formatDate(row.last_crawl_time)}</td>
                <td className="px-3 py-1.5">{formatNumber(row.word_count)}</td>
                <td className="px-3 py-1.5">{row.http_status ?? '—'}</td>
              </tr>
            ))}
            {list && list.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                  No URLs match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <span className="text-muted-foreground">
            Page {page + 1} of {pages}
          </span>
          <Button size="sm" variant="outline" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      )}

      {selected && (
        <UrlDrawer
          projectId={projectId}
          url={selected}
          canInspect={!isDemo}
          hasSearchConsole={summary.has_search_console}
          onClose={() => setSelected(null)}
          onInspected={() => setReload((n) => n + 1)}
        />
      )}
    </div>
  )
}
