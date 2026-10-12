import * as React from 'react'
import { cn } from '@/lib/utils'

/** A loading placeholder. Wrap it in LoadingBlock so screen readers and tests still see a "Loading…" state. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

export function LoadingBlock({ children = <Skeleton className="h-24 w-full" /> }: { children?: React.ReactNode }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {children}
    </div>
  )
}
