import axios from 'axios'
import { api } from './api'
import type {
  CandidateStatus,
  DecidableStatus,
  IndexedUrlList,
  IndexingOverviewItem,
  IndexingSummary,
  InspectionBudget,
  KeywordCandidate,
  KeywordList,
  KeywordRun,
  McpToken,
  Rankings,
  ReportData,
  SettingsData,
  SitemapInfo,
  UrlDetail,
} from './indexingTypes'

export async function fetchIndexingSummary(projectId: string): Promise<IndexingSummary> {
  return (await api.get<IndexingSummary>(`/projects/${projectId}/indexing`)).data
}

export async function fetchIndexedUrls(
  projectId: string,
  params: { issue?: string; q?: string; limit: number; offset: number },
): Promise<IndexedUrlList> {
  return (await api.get<IndexedUrlList>(`/projects/${projectId}/indexing/urls`, { params })).data
}

export async function fetchUrlDetail(projectId: string, urlId: string): Promise<UrlDetail> {
  return (await api.get<UrlDetail>(`/projects/${projectId}/indexing/urls/${urlId}`)).data
}

export async function inspectUrlNow(projectId: string, url: string): Promise<{ budget: InspectionBudget }> {
  return (await api.post(`/projects/${projectId}/indexing/inspect`, { url })).data
}

export async function fetchSitemaps(projectId: string): Promise<SitemapInfo> {
  return (await api.get<SitemapInfo>(`/projects/${projectId}/sitemaps`)).data
}

export async function fetchIndexingOverview(): Promise<IndexingOverviewItem[]> {
  return (await api.get<IndexingOverviewItem[]>('/indexing/overview')).data
}

export async function fetchKeywords(projectId: string, status?: CandidateStatus): Promise<KeywordList> {
  return (await api.get<KeywordList>(`/projects/${projectId}/keywords`, { params: status ? { status } : {} })).data
}

export async function startKeywordRun(projectId: string): Promise<KeywordRun> {
  return (await api.post<KeywordRun>(`/projects/${projectId}/keywords/runs`)).data
}

export async function setCandidateStatus(candidateId: string, status: DecidableStatus): Promise<KeywordCandidate> {
  return (await api.patch<KeywordCandidate>(`/keywords/${candidateId}`, { status })).data
}

export async function bulkSetStatus(projectId: string, ids: string[], status: DecidableStatus): Promise<number> {
  return (await api.post<{ updated: number }>(`/projects/${projectId}/keywords/bulk`, { ids, status })).data.updated
}

export async function exportKeywordQueue(projectId: string): Promise<{ count: number; path: string | null }> {
  return (await api.post(`/projects/${projectId}/keywords/export`)).data
}

export async function fetchReport(name: string, project?: string): Promise<ReportData> {
  return (await api.get<ReportData>(`/reports/${name}`, { params: project ? { project } : {} })).data
}

// The CSV needs the bearer token, so it is fetched through axios and handed to the browser as a download.
export async function downloadReportCsv(name: string, project?: string): Promise<void> {
  const resp = await api.get<Blob>(`/reports/${name}`, {
    params: { format: 'csv', ...(project ? { project } : {}) },
    responseType: 'blob',
  })
  const href = URL.createObjectURL(resp.data)
  const link = document.createElement('a')
  link.href = href
  link.download = `helm-${name}${project ? `-${project}` : ''}.csv`
  link.click()
  URL.revokeObjectURL(href)
}

export async function fetchSettings(): Promise<SettingsData> {
  return (await api.get<SettingsData>('/settings')).data
}

export async function putSetting(key: string, value: unknown): Promise<void> {
  await api.put(`/settings/${key}`, { value })
}

export async function fetchMcpTokens(): Promise<McpToken[]> {
  return (await api.get<McpToken[]>('/mcp-tokens')).data
}

export async function createMcpToken(
  label: string,
  scope: 'read' | 'write',
  projectSlugs: string[] | null = null,
): Promise<McpToken & { token: string }> {
  return (await api.post('/mcp-tokens', { label, scope, project_slugs: projectSlugs })).data
}

export async function fetchRankings(projectId: string, weeks: number, minImpressions: number): Promise<Rankings> {
  return (await api.get<Rankings>(`/projects/${projectId}/rankings`, { params: { weeks, min_impressions: minImpressions, limit: 500 } })).data
}

/** The manual alternative to the weekly rollup. Rejects with a 409 or 429 whose detail says why. */
export async function refreshRankings(projectId: string): Promise<void> {
  await api.post(`/projects/${projectId}/rankings/refresh`)
}

export async function revokeMcpToken(id: string): Promise<void> {
  await api.delete(`/mcp-tokens/${id}`)
}

/** The server's own message for a failed request, e.g. "inspection_budget: must be between 0 and 1500". */
export function errorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}
