import * as React from 'react'
import { Link } from 'react-router-dom'
import { Badge, SeverityBadge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { useAuth } from '@/contexts/AuthContext'
import { fetchTrafficOverview } from '@/lib/api'
import { formatCollectedAt, formatNumber, formatPct, isStale } from '@/lib/traffic'
import type { TrafficOverviewItem, TrafficTrend } from '@/lib/types'

function TrendCell({ trend }: { trend: TrafficTrend | null }) {
  if (!trend) return <span className="text-muted-foreground">—</span>
  const pct = formatPct(trend)
  return (
    <span className="flex flex-col">
      <span className="font-medium">{formatNumber(trend.recent)}</span>
      {pct && <span className={trend.pct_change! < 0 ? 'text-xs text-destructive' : 'text-xs text-severity-green'}>{pct}</span>}
    </span>
  )
}

export function TrafficPage() {
  const { isDemo } = useAuth()
  const [items, setItems] = React.useState<TrafficOverviewItem[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    fetchTrafficOverview()
      .then(setItems)
      .catch(() => setError('Failed to load traffic overview.'))
  }, [])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!items) return <p className="text-sm text-muted-foreground">Loading…</p>

  const connected = items.filter((i) => i.configured)
  const notConnected = items.filter((i) => !i.configured)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Search traffic</h1>
        <p className="text-sm text-muted-foreground">
          Search Console and Google Analytics, last 7 days compared with the 7 before. Search Console data trails by 3 days.
        </p>
      </div>

      {connected.length === 0 ? (
        <Card>
          <CardContent className="p-4 text-sm text-muted-foreground">
            No site is connected to Search Console or Analytics yet.
          </CardContent>
        </Card>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card" tabIndex={0}>
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                {['Site', 'Status', 'Clicks', 'Impressions', 'Sessions', 'Last collected'].map((h) => (
                  <th key={h} className="px-4 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {connected.map((item) => (
                <tr key={item.project_id} className="border-t border-border align-top">
                  <td className="px-4 py-3">
                    <Link to={`/projects/${item.project_id}#traffic`} className="font-medium hover:underline">
                      {item.name}
                    </Link>
                    {item.alert_messages && item.alert_messages.length > 0 && (
                      <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
                        {item.alert_messages.map((a) => (
                          <li key={a.message}>{a.message}</li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={item.alert_severity} />
                  </td>
                  <td className="px-4 py-3">
                    <TrendCell trend={item.clicks} />
                  </td>
                  <td className="px-4 py-3">
                    <TrendCell trend={item.impressions} />
                  </td>
                  <td className="px-4 py-3">
                    <TrendCell trend={item.sessions} />
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    <span className="block">{formatCollectedAt(item.last_collected_at)}</span>
                    {!isDemo && isStale(item.last_collected_at) && <Badge variant="yellow">Stale</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {notConnected.length > 0 && (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-muted-foreground">Not connected</h2>
          <ul className="flex flex-wrap gap-2">
            {notConnected.map((item) => (
              <li key={item.project_id}>
                <Link
                  to={`/projects/${item.project_id}#traffic`}
                  className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                >
                  {item.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
