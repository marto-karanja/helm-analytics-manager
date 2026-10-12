import { useId } from 'react'
import { cn } from '@/lib/utils'

interface LogoProps {
  variant?: 'mark' | 'lockup'
  /** Height of the tile in px. */
  size?: number
  /** Show the "Analytics Manager" line under the wordmark (lockup only). */
  tagline?: boolean
  className?: string
}

/** The H-with-trend mark. A gradient tile with a white glyph; reads at 16 px. */
function Mark({ size, decorative }: { size: number; decorative: boolean }) {
  const id = useId()
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : 'Helm'}
      className="shrink-0"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="1" stopColor="#14b8a6" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill={`url(#${id})`} />
      <path d="M21 17V47M43 17V47M21 38L43 27" fill="none" stroke="#fff" strokeWidth="6" strokeLinecap="round" />
      <circle cx="43" cy="27" r="4.5" fill="#fff" />
    </svg>
  )
}

export function Logo({ variant = 'lockup', size = 28, tagline = false, className }: LogoProps) {
  if (variant === 'mark') {
    return (
      <span className={className}>
        <Mark size={size} decorative={false} />
      </span>
    )
  }
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <Mark size={size} decorative />
      <span className="flex flex-col leading-none">
        <span className="font-semibold tracking-tight" style={{ fontSize: size * 0.72 }}>
          Helm
        </span>
        {tagline && <span className="mt-1 text-xs font-normal text-muted-foreground">Analytics Manager</span>}
      </span>
    </span>
  )
}
