import { useId } from 'react'

interface SparklineProps {
  /** Oldest first. Null entries are gaps. */
  values: (number | null)[]
  label: string
  width?: number
  height?: number
  /** A CSS colour or token, e.g. `var(--color-chart-1)`. */
  color?: string
  className?: string
}

/** A tiny line with a soft area fill. Needs two or more real values; otherwise draws nothing. */
export function Sparkline({ values, label, width = 96, height = 28, color = 'var(--color-chart-1)', className }: SparklineProps) {
  const id = useId()
  const real = values.filter((v): v is number => v !== null)
  if (real.length < 2) return null
  const min = Math.min(...real)
  const max = Math.max(...real)
  const span = max - min || 1
  const pad = 3
  const x = (i: number) => (i / (values.length - 1)) * width
  const y = (v: number) => height - pad - ((v - min) / span) * (height - pad * 2)

  // One path per run of consecutive values, so a gap stays a gap instead of being drawn across.
  const runs: { i: number; v: number }[][] = []
  values.forEach((v, i) => {
    if (v === null) {
      runs.push([])
    } else {
      if (runs.length === 0) runs.push([])
      runs[runs.length - 1].push({ i, v })
    }
  })
  const lines = runs.filter((r) => r.length > 0)
  const line = (r: { i: number; v: number }[]) => r.map((p, k) => `${k === 0 ? 'M' : 'L'}${x(p.i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' ')
  const area = (r: { i: number; v: number }[]) => `${line(r)} L${x(r[r.length - 1].i).toFixed(1)} ${height} L${x(r[0].i).toFixed(1)} ${height} Z`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className={className}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {lines.filter((r) => r.length > 1).map((r, k) => (
        <path key={`a${k}`} d={area(r)} fill={`url(#${id})`} />
      ))}
      {lines.map((r, k) => (
        <path key={`l${k}`} d={line(r)} fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      ))}
    </svg>
  )
}
