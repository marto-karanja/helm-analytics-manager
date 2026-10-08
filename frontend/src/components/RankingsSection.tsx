import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import { errorMessage, fetchRankings, refreshRankings } from '@/lib/indexingApi'
import { formatDateTime, shortPath } from '@/lib/indexing'
import type { RankedPage, Rankings } from '@/lib/indexingTypes'
import { formatNumber } from '@/lib/traffic'

function Change({ value }: { value: number | null }) {
  if (value === null) return <span className="text-muted-foreground">new</span>
  if (Math.abs(value) < 0.05) return <span className="text-muted-foreground">0.0</span>
  return <span className={value > 0 ? 'text-green-600' : 'text-red-600'}>{value > 0 ? `+${value.toFixed(1)}` : value.toFixed(1)}</span>
}

export function RankingsSection({ projectId, isDemo }: { projectId: string; isDemo: boolean }) {
  const [weeks, setWeeks] = React.useState(4)
  const [minImpressions, setMinImpressions] = React.useState('10')
  const [filter, setFilter] = React.useState('')
  const [data, setData] = React.useState<Rankings | null>(null)
  const [message, setMessage] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [loadFailed, setLoadFailed] = React.useState(false)

  const load = React.useCallback(() => {
    fetchRankings(projectId, weeks, Number(minImpressions) || 0)
      .then((d) => {
        setLoadFailed(false)
        setData(d)
      })
      .catch((err) => {
        setLoadFailed(true)
        setMessage(errorMessage(err, 'Could not load rankings.'))
      })
  }, [projectId, weeks, minImpressions])

  React.useEffect(() => {
    load()
  }, [load])

  // While a manual refresh is waiting for the collector, check again every 15 seconds.
  React.useEffect(() => {
    if (!data?.refresh_pending) return
    const timer = window.setInterval(load, 15000)
    return () => window.clearInterval(timer)
  }, [data?.refresh_pending, load])

  async function refresh() {
    setBusy(true)
    setMessage(null)
    try {
      await refreshRankings(projectId)
      setMessage('Queued. The collector runs it within about a minute.')
      load()
    } catch (err) {
      setMessage(errorMessage(err, 'Could not queue the refresh.'))
    } finally {
      setBusy(false)
    }
  }

  const pages: RankedPage[] = (data?.pages ?? []).filter((p) => p.url.toLowerCase().includes(filter.toLowerCase()))

  return (
    <Card>
      <CardHeader className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">Page rankings</CardTitle>
          <Button size="sm" disabled={busy || isDemo || data?.refresh_pending} onClick={refresh}>
            {data?.refresh_pending ? 'Refresh queued…' : busy ? 'Queuing…' : 'Refresh now'}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Average position per page, weighted by impressions across its queries (lower is better; the change is green when the page moved up). Updated
          weekly; "Refresh now" pulls fresh data on demand, at most once every 30 minutes. Search Console data trails by about 3 days.
          {data?.last_refreshed_at ? ` Last refreshed ${formatDateTime(data.last_refreshed_at)}.` : ''}
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <Select value={String(weeks)} onChange={(e) => setWeeks(Number(e.target.value))} aria-label="Window">
            {[1, 2, 4, 8, 12].map((w) => (
              <option key={w} value={w}>
                Last {w} week{w > 1 ? 's' : ''}
              </option>
            ))}
          </Select>
          <Input className="w-28" type="number" min={0} value={minImpressions} onChange={(e) => setMinImpressions(e.target.value)} aria-label="Minimum impressions" />
          <Input className="w-56" placeholder="Filter by URL" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        {message && <p className="text-sm text-muted-foreground">{message}</p>}
      </CardHeader>
      <CardContent>
        {data === null ? (
          <p className="text-sm text-muted-foreground">{loadFailed ? 'Rankings could not be loaded.' : 'Loading rankings…'}</p>
        ) : data.pages.length === 0 ? (
          <p className="text-sm text-muted-foreground">{data.note ?? 'No pages meet the impression threshold in this window.'}</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-card text-left text-muted-foreground">
                <tr>
                  {['Page', 'Position', 'Change', 'Clicks', 'Impr.', 'Top query', 'Indexing'].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pages.map((p) => (
                  <tr key={p.url} className="border-t border-border">
                    <td className="max-w-xs truncate px-3 py-1.5" title={p.url}>
                      {shortPath(p.url)}
                    </td>
                    <td className="px-3 py-1.5">{p.position?.toFixed(1) ?? '–'}</td>
                    <td className="px-3 py-1.5">
                      <Change value={p.position_change} />
                    </td>
                    <td className="px-3 py-1.5">{formatNumber(p.clicks)}</td>
                    <td className="px-3 py-1.5">{formatNumber(p.impressions)}</td>
                    <td className="max-w-xs truncate px-3 py-1.5" title={p.top_queries[0]?.query}>
                      {p.top_queries[0] ? `${p.top_queries[0].query} (${p.top_queries[0].position?.toFixed(1) ?? '–'})` : '–'}
                    </td>
                    <td className="px-3 py-1.5">{p.indexing ? <Badge variant="muted">{p.indexing}</Badge> : <span className="text-muted-foreground">–</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
