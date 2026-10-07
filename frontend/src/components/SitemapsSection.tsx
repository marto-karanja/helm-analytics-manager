import * as React from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { formatDateTime } from '@/lib/indexing'
import { fetchSitemaps } from '@/lib/indexingApi'
import type { SitemapInfo } from '@/lib/indexingTypes'
import { formatNumber } from '@/lib/traffic'

export function SitemapsSection({ projectId }: { projectId: string }) {
  const [data, setData] = React.useState<SitemapInfo | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    fetchSitemaps(projectId)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError('Failed to load sitemaps.'))
    return () => {
      cancelled = true
    }
  }, [projectId])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>

  if (!data.has_search_console && data.sitemaps.length === 0) {
    return (
      <Card>
        <CardContent className="p-4 text-sm text-muted-foreground">
          This project has no Search Console property, so Google's view of its sitemaps is not available.
          {data.urls_by_source.length > 0 && ' The URLs Helm found by walking them are listed below.'}
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-card text-left text-muted-foreground">
            <tr>
              {['Sitemap', 'Last submitted', 'Last downloaded by Google', 'Errors', 'Warnings', 'URLs (Google)', 'URLs (Helm)'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.sitemaps.map((s) => (
              <tr key={s.path} className="border-t border-border">
                <td className="max-w-xs break-all px-3 py-1.5">
                  {s.path}
                  {s.is_pending && (
                    <Badge variant="yellow" className="ml-2">
                      Pending
                    </Badge>
                  )}
                </td>
                <td className="px-3 py-1.5 whitespace-nowrap">{formatDateTime(s.last_submitted)}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{formatDateTime(s.last_downloaded)}</td>
                <td className="px-3 py-1.5">{s.errors > 0 ? <Badge variant="red">{s.errors}</Badge> : 0}</td>
                <td className="px-3 py-1.5">{s.warnings > 0 ? <Badge variant="yellow">{s.warnings}</Badge> : 0}</td>
                <td className="px-3 py-1.5">{formatNumber(s.submitted_urls)}</td>
                <td className="px-3 py-1.5">{formatNumber(s.urls_found_by_helm)}</td>
              </tr>
            ))}
            {data.sitemaps.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                  Search Console has not reported any sitemaps for this property yet. The collector checks daily.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data.urls_by_source.length > 0 && (
        <Card>
          <CardContent className="p-4 text-sm">
            <p className="mb-2 font-medium">URLs found by walking the sitemaps</p>
            <ul className="flex flex-col gap-1 text-muted-foreground">
              {data.urls_by_source.map((u) => (
                <li key={u.sitemap ?? 'unknown'} className="flex justify-between gap-4">
                  <span className="break-all">{u.sitemap ?? 'unknown source'}</span>
                  <span>{formatNumber(u.urls)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
