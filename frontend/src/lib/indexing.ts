import type { IndexIssue } from './indexingTypes'

type BadgeVariant = 'green' | 'yellow' | 'red' | 'muted' | 'outline'

export const ISSUE_ORDER: IndexIssue[] = [
  'indexed',
  'crawled_not_indexed',
  'discovered_not_indexed',
  'thin',
  'duplicate_risk',
  'blocked',
  'fetch_error',
  'unknown',
]

export const ISSUE_LABEL: Record<IndexIssue, string> = {
  indexed: 'Indexed',
  crawled_not_indexed: 'Crawled, not indexed',
  discovered_not_indexed: 'Discovered, not indexed',
  thin: 'Thin content',
  duplicate_risk: 'Duplicate risk',
  blocked: 'Blocked',
  fetch_error: 'Fetch error',
  unknown: 'Not checked yet',
}

export const ISSUE_HINT: Record<IndexIssue, string> = {
  indexed: 'Google reports the page as indexed.',
  crawled_not_indexed: 'Google fetched it and chose not to index it. Usually a quality or duplication signal.',
  discovered_not_indexed: 'Google knows the URL but has not crawled it yet.',
  thin: 'Below the word-count threshold in Settings.',
  duplicate_risk: 'Same content or the same title as another URL.',
  blocked: 'noindex, a robots.txt block, or a canonical pointing at another URL.',
  fetch_error: 'The page returned an error or timed out.',
  unknown: 'Neither fetched nor inspected yet.',
}

export function issueVariant(issue: IndexIssue): BadgeVariant {
  switch (issue) {
    case 'indexed':
      return 'green'
    case 'crawled_not_indexed':
    case 'discovered_not_indexed':
    case 'thin':
    case 'duplicate_risk':
      return 'yellow'
    case 'blocked':
    case 'fetch_error':
      return 'red'
    default:
      return 'muted'
  }
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : '—'
}

export function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleDateString() : '—'
}

export function shortPath(url: string): string {
  try {
    const u = new URL(url)
    return (u.pathname + u.search) || '/'
  } catch {
    return url
  }
}
