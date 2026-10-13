import * as React from 'react'
import { cn } from '@/lib/utils'

/** A loading placeholder. Wrap it in LoadingBlock so screen readers and tests still see a "Loading…" state. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

/** The default placeholder while a page or section fetches: a title bar and a few content blocks. */
export function PageLoading() {
  return (
    <LoadingBlock>
      <div className="flex flex-col gap-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    </LoadingBlock>
  )
}

export function LoadingBlock({ children = <Skeleton className="h-24 w-full" /> }: { children?: React.ReactNode }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {children}
    </div>
  )
}
