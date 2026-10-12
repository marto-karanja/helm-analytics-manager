import * as React from 'react'
import { cn } from '@/lib/utils'

/** A compact table in a scrolling frame: sticky header, row hover, tabular numerals. Use `numeric` cells for numbers. */
export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="max-h-[70vh] overflow-auto rounded-lg border border-border bg-card shadow-card">
      <table className={cn('w-full text-sm', className)} {...props} />
    </div>
  )
}

export function THead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn('sticky top-0 z-10 bg-card text-left text-muted-foreground shadow-[0_1px_0_var(--color-border)]', className)} {...props} />
}

export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn('border-t border-border transition-colors first:border-t-0 hover:bg-muted/50', className)} {...props} />
}

interface CellProps {
  numeric?: boolean
  /** On narrow screens, keep this column pinned while the rest scrolls. */
  sticky?: boolean
}

export function TH({ className, numeric, sticky, ...props }: React.ThHTMLAttributes<HTMLTableCellElement> & CellProps) {
  return <th className={cn('px-4 py-2 font-medium', numeric && 'text-right', sticky && 'sticky left-0 bg-card', className)} {...props} />
}

export function TD({ className, numeric, sticky, ...props }: React.TdHTMLAttributes<HTMLTableCellElement> & CellProps) {
  return <td className={cn('px-4 py-2', numeric && 'text-right tabular-nums', sticky && 'sticky left-0 bg-card', className)} {...props} />
}
