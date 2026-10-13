/** Shared look for every chart: axis text, the tooltip card, and the six-colour palette from the design tokens. */
export const AXIS_TICK = { fontSize: 12, fill: 'var(--color-muted-foreground)' }
export const AXIS_LINE = 'var(--color-border)'

export const TOOLTIP_STYLE = {
  background: 'var(--color-card)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  fontSize: 12,
  padding: '8px 10px',
  boxShadow: 'var(--shadow-card-hover)',
}

/** Spread onto a recharts <Tooltip>. */
export const TOOLTIP_PROPS = {
  contentStyle: TOOLTIP_STYLE,
  labelStyle: { color: 'var(--color-card-foreground)', fontWeight: 600, marginBottom: 2 },
  itemStyle: { color: 'var(--color-card-foreground)', padding: 0 },
  cursor: { stroke: 'var(--color-border)' },
} as const

export const CHART = {
  indigo: 'var(--color-chart-1)',
  teal: 'var(--color-chart-2)',
  orange: 'var(--color-chart-3)',
  pink: 'var(--color-chart-4)',
  olive: 'var(--color-chart-5)',
  sky: 'var(--color-chart-6)',
} as const
