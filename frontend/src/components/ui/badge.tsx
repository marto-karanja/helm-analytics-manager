import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground',
        outline: 'border border-border text-foreground',
        green: 'bg-severity-green text-severity-green-foreground',
        yellow: 'bg-severity-yellow text-severity-yellow-foreground',
        red: 'bg-severity-red text-severity-red-foreground',
        muted: 'bg-muted text-muted-foreground',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />
}

export function SeverityBadge({ severity }: { severity: string | null | undefined }) {
  const variant = severity === 'red' ? 'red' : severity === 'yellow' ? 'yellow' : severity === 'green' ? 'green' : 'muted'
  const label = severity ? severity.toUpperCase() : 'N/A'
  return <Badge variant={variant}>{label}</Badge>
}
