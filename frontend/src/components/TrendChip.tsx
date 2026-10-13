import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'

/** A percentage change as a tinted chip with an arrow. Null (no prior period) renders nothing. */
export function TrendChip({ pct, className }: { pct: number | null | undefined; className?: string }) {
  if (pct === null || pct === undefined) return null
  const up = pct > 0
  const flat = pct === 0
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-xs font-medium tabular-nums',
        flat
          ? 'bg-muted text-muted-foreground'
          : up
            ? 'bg-severity-green-soft text-severity-green-soft-foreground'
            : 'bg-severity-red-soft text-severity-red-soft-foreground',
        className,
      )}
    >
      <Icon size={12} aria-hidden />
      <span>
        {up ? '+' : ''}
        {pct}%
      </span>
    </span>
  )
}
