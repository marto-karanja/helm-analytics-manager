// Contrast gate for the design tokens in src/index.css. Run: npm run check:contrast
// Text pairs need 4.5:1 (WCAG AA), UI/graphic pairs 3:1. Exits 1 on any failure.
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')

function tokens(block) {
  const out = {}
  for (const m of block.matchAll(/--color-([\w-]+):\s*oklch\(([^)]+)\)/g)) {
    const [l, c, h] = m[2].split('/')[0].trim().split(/\s+/).map(Number)
    out[m[1]] = { l, c, h, alpha: m[2].includes('/') ? Number(m[2].split('/')[1]) : 1 }
  }
  return out
}

const themeBlock = css.match(/@theme\s*{([\s\S]*?)\n}/)[1]
const darkBlock = css.match(/\.dark\s*{([\s\S]*?)\n}/)[1]
const light = tokens(themeBlock)
const dark = { ...light, ...tokens(darkBlock) }

function toSrgb({ l, c, h }) {
  const hr = (h * Math.PI) / 180
  const a = c * Math.cos(hr)
  const b = c * Math.sin(hr)
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ].map((v) => Math.min(1, Math.max(0, v))) // linear sRGB, clipped to gamut
}

const luminance = (t) => {
  const [r, g, b] = toSrgb(t)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function ratio(fg, bg) {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const TEXT = 4.5
const UI = 3
// [foreground token, background token, minimum ratio, where it is used]
const pairs = [
  ['foreground', 'background', TEXT, 'body text'],
  ['card-foreground', 'card', TEXT, 'card text'],
  ['muted-foreground', 'background', TEXT, 'secondary text on page'],
  ['muted-foreground', 'card', TEXT, 'secondary text on card'],
  ['muted-foreground', 'muted', TEXT, 'secondary text on muted'],
  ['primary-foreground', 'primary', TEXT, 'primary button'],
  ['accent-foreground', 'accent', TEXT, 'active nav, hover'],
  ['brand', 'background', TEXT, 'links on page'],
  ['brand', 'card', TEXT, 'links on card'],
  ['destructive-foreground', 'destructive', TEXT, 'destructive button'],
  ['destructive', 'card', TEXT, 'error and negative trend text on card'],
  ['destructive', 'background', TEXT, 'error text on page'],
  ['severity-green', 'card', TEXT, 'positive trend text on card'],
  ['severity-green', 'background', TEXT, 'positive trend text on page'],
  ['severity-green-foreground', 'severity-green', TEXT, 'solid green badge'],
  ['severity-yellow-foreground', 'severity-yellow', TEXT, 'solid yellow badge'],
  ['severity-red-foreground', 'severity-red', TEXT, 'solid red (critical) badge'],
  ['severity-green-soft-foreground', 'severity-green-soft', TEXT, 'soft green badge'],
  ['severity-yellow-soft-foreground', 'severity-yellow-soft', TEXT, 'soft yellow badge'],
  ['severity-red-soft-foreground', 'severity-red-soft', TEXT, 'soft red badge'],
  ['brand', 'card', UI, 'focus ring and active indicator'],
  ['severity-red', 'card', UI, 'critical line in charts'],
  ...[1, 2, 3, 4, 5, 6].map((n) => [`chart-${n}`, 'card', UI, `chart colour ${n}`]),
]

let failures = 0
for (const [name, theme] of [['light', light], ['dark', dark]]) {
  for (const [fg, bg, min, use] of pairs) {
    if (!theme[fg] || !theme[bg]) {
      console.log(`FAIL ${name}: unknown token ${!theme[fg] ? fg : bg}`)
      failures++
      continue
    }
    const r = ratio(theme[fg], theme[bg])
    const ok = r >= min
    if (!ok) failures++
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name.padEnd(5)} ${r.toFixed(2).padStart(5)} (min ${min})  ${fg} on ${bg}  - ${use}`)
  }
}
console.log(failures ? `\n${failures} pair(s) below threshold` : '\nAll token pairs pass')
process.exit(failures ? 1 : 0)
