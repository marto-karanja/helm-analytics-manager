import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva('inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold', {
  variants: {
    variant: {
      default: 'bg-primary text-primary-foreground',
      outline: 'border border-border text-foreground',
      // Soft tints: tinted background, strong text and a small dot. Solid red is kept for critical only.
      green: 'bg-severity-green-soft text-severity-green-soft-foreground',
      yellow: 'bg-severity-yellow-soft text-severity-yellow-soft-foreground',
      red: 'bg-severity-red text-severity-red-foreground',
      muted: 'bg-muted text-muted-foreground',
    },
  },
  defaultVariants: {
    variant: 'default',
  },
})

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {
  dot?: boolean
}

export function Badge({ className, variant, dot = false, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  const variant = severity === 'red' ? 'red' : severity === 'yellow' ? 'yellow' : severity === 'green' ? 'green' : 'muted'
  const label = severity ? severity.toUpperCase() : 'N/A'
  return (
    <Badge variant={variant} dot={variant !== 'muted'}>
      {label}
    </Badge>
  )
}
