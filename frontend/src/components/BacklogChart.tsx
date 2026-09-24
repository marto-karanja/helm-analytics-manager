import * as React from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PipelineSnapshot } from '@/lib/types'

const AXIS_TICK = { fontSize: 12, fill: 'var(--color-muted-foreground)' }

export function BacklogChart({ snapshots }: { snapshots: PipelineSnapshot[] }) {
  const data = React.useMemo(
    () =>
      [...snapshots]
        .reverse()
        .map((s) => ({
          date: new Date(s.synced_at).toLocaleDateString(),
          backlog: s.backlog_count,
          blocked: s.blocked_count,
        })),
    [snapshots],
  )

  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">No backlog history yet.</p>
  }

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="date" tick={AXIS_TICK} stroke="var(--color-border)" />
        <YAxis tick={AXIS_TICK} stroke="var(--color-border)" allowDecimals={false} />
        <Tooltip
          contentStyle={{
            background: 'var(--color-card)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            fontSize: 12,
          }}
          labelStyle={{ color: 'var(--color-card-foreground)' }}
          itemStyle={{ color: 'var(--color-card-foreground)' }}
          cursor={{ stroke: 'var(--color-border)' }}
        />
        <Line
          type="monotone"
          dataKey="backlog"
          stroke="var(--color-primary)"
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
