import * as React from 'react'
import { EmptyState } from '@/components/ui/empty-state'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS_LINE, AXIS_TICK, CHART, TOOLTIP_PROPS } from '@/lib/chartTheme'
import type { PipelineSnapshot } from '@/lib/types'

export function BacklogChart({ snapshots }: { snapshots: PipelineSnapshot[] }) {
  const data = React.useMemo(
    () =>
      [...snapshots]
        .reverse()
        .map((s) => ({
          date: new Date(s.synced_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
          backlog: s.backlog_count,
          blocked: s.blocked_count,
        })),
    [snapshots],
  )

  if (data.length === 0) {
    return <EmptyState title="No backlog history yet" description="The chart appears after the pipeline has synced a few times." className="py-6" />
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="date" tick={AXIS_TICK} stroke={AXIS_LINE} minTickGap={32} />
        <YAxis tick={AXIS_TICK} stroke={AXIS_LINE} allowDecimals={false} />
        <Tooltip {...TOOLTIP_PROPS} />
        <Line
          type="monotone"
          dataKey="backlog"
          stroke={CHART.indigo}
          strokeWidth={2}
          dot={false}
          activeDot={{ stroke: 'var(--color-card)' }}
        />
        <Line
          type="monotone"
          dataKey="blocked"
          stroke="var(--color-severity-red)"
          strokeWidth={2}
          dot={false}
          activeDot={{ stroke: 'var(--color-card)' }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
