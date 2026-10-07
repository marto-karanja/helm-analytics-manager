import * as React from 'react'
import { Copy } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Label, Select } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'
import { fetchProjects } from '@/lib/api'
import {
  createMcpToken,
  errorMessage,
  fetchMcpTokens,
  fetchSettings,
  putSetting,
  revokeMcpToken,
} from '@/lib/indexingApi'
import { formatDateTime } from '@/lib/indexing'
import type { McpToken, SettingsData } from '@/lib/indexingTypes'
import type { Project } from '@/lib/types'

const WEIGHTS = ['demand', 'gap', 'relevance', 'competition'] as const

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function SaveRow({ onSave, saving, message }: { onSave: () => void; saving: boolean; message: string | null }) {
  return (
    <div className="flex items-center gap-3">
      <Button size="sm" disabled={saving} onClick={onSave}>
        {saving ? 'Saving…' : 'Save'}
      </Button>
      {message && <span className="text-sm text-muted-foreground">{message}</span>}
    </div>
  )
}

function useSaver() {
  const [saving, setSaving] = React.useState(false)
  const [message, setMessage] = React.useState<string | null>(null)
  async function save(entries: [string, unknown][]) {
    setSaving(true)
    setMessage(null)
    try {
      for (const [key, value] of entries) await putSetting(key, value)
      setMessage('Saved.')
    } catch (err) {
      setMessage(errorMessage(err, 'Could not save.'))
    } finally {
      setSaving(false)
    }
  }
  return { saving, message, save }
}

function IndexingSettings({ data, projects, editable }: { data: SettingsData; projects: Project[]; editable: boolean }) {
  const [budget, setBudget] = React.useState(String(data.values.inspection_budget))
  const [thin, setThin] = React.useState(String(data.values.thin_word_threshold))
  const [split, setSplit] = React.useState<Record<string, string>>(
    Object.fromEntries(Object.entries(data.values.inspection_budget_split).map(([k, v]) => [k, String(v)])),
  )
  const { saving, message, save } = useSaver()
  const ceiling = data.limits.inspection_ceiling

  function submit() {
    const splitValues = Object.fromEntries(
      Object.entries(split)
        .filter(([, v]) => v.trim() !== '')
        .map(([k, v]) => [k, Number(v)]),
    )
    save([
      ['inspection_budget', Number(budget)],
      ['inspection_budget_split', splitValues],
      ['thin_word_threshold', Number(thin)],
    ])
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Indexing</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Daily URL inspections" hint={`Across all projects. The server never spends more than ${ceiling.toLocaleString()} a day, whatever is saved here.`}>
            <Input type="number" min={0} max={ceiling} disabled={!editable} value={budget} onChange={(e) => setBudget(e.target.value)} />
          </Field>
          <Field label="Thin-content threshold (words)" hint="Pages below this are flagged thin.">
            <Input type="number" min={50} max={5000} disabled={!editable} value={thin} onChange={(e) => setThin(e.target.value)} />
          </Field>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Per-project daily cap (optional)</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <div key={p.id} className="flex items-center gap-2">
                <span className="w-40 truncate text-sm text-muted-foreground" title={p.name}>
                  {p.name}
                </span>
                <Input
                  type="number"
                  min={0}
                  max={ceiling}
                  placeholder="no cap"
                  aria-label={`Daily cap for ${p.name}`}
                  disabled={!editable}
                  value={split[p.slug] ?? ''}
                  onChange={(e) => setSplit({ ...split, [p.slug]: e.target.value })}
                />
              </div>
            ))}
          </div>
        </div>
        {editable && <SaveRow onSave={submit} saving={saving} message={message} />}
      </CardContent>
    </Card>
  )
}

function KeywordSettings({ data, editable }: { data: SettingsData; editable: boolean }) {
  const [source, setSource] = React.useState(data.values.volume_source)
  const [cap, setCap] = React.useState(String(data.values.llm_daily_cap_usd))
  const [weights, setWeights] = React.useState<Record<string, string>>(
    Object.fromEntries(WEIGHTS.map((w) => [w, String(data.values.scoring_weights[w])])),
  )
  const { saving, message, save } = useSaver()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Keywords</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Volume source" hint="Keyword Planner needs Google Ads credentials on the server; without them Search Console impressions are used.">
            <Select disabled={!editable} value={source} onChange={(e) => setSource(e.target.value as typeof source)}>
              <option value="gsc_proxy">Search Console impressions</option>
              <option value="keyword_planner">Keyword Planner, then Search Console</option>
            </Select>
          </Field>
          <Field label="Daily Claude spend cap (USD)" hint="Generator runs stop once today's recorded cost reaches this.">
            <Input type="number" min={0} max={100} step={0.5} disabled={!editable} value={cap} onChange={(e) => setCap(e.target.value)} />
          </Field>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Score weights</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {WEIGHTS.map((w) => (
              <Field key={w} label={w.charAt(0).toUpperCase() + w.slice(1)}>
                <Input
                  type="number"
                  min={0}
                  max={10}
                  step={0.1}
                  disabled={!editable}
                  value={weights[w]}
                  onChange={(e) => setWeights({ ...weights, [w]: e.target.value })}
                />
              </Field>
            ))}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">Competition is advertiser competition, a weak signal, so it starts low.</p>
        </div>
        {editable && (
          <SaveRow
            saving={saving}
            message={message}
            onSave={() =>
              save([
                ['volume_source', source],
                ['llm_daily_cap_usd', Number(cap)],
                ['scoring_weights', Object.fromEntries(WEIGHTS.map((w) => [w, Number(weights[w])]))],
              ])
            }
          />
        )}
      </CardContent>
    </Card>
  )
}

function McpTokens() {
  const [tokens, setTokens] = React.useState<McpToken[] | null>(null)
  const [label, setLabel] = React.useState('')
  const [scope, setScope] = React.useState<'read' | 'write'>('read')
  const [fresh, setFresh] = React.useState<{ label: string; token: string } | null>(null)
  const [message, setMessage] = React.useState<string | null>(null)
  const [copied, setCopied] = React.useState(false)

  const load = React.useCallback(() => fetchMcpTokens().then(setTokens).catch(() => setMessage('Failed to load tokens.')), [])
  React.useEffect(() => {
    load()
  }, [load])

  async function create() {
    setMessage(null)
    try {
      const created = await createMcpToken(label.trim(), scope)
      setFresh({ label: created.label, token: created.token })
      setLabel('')
      setCopied(false)
      load()
    } catch (err) {
      setMessage(errorMessage(err, 'Could not create the token.'))
    }
  }

  async function revoke(id: string) {
    await revokeMcpToken(id)
    load()
  }

  async function copy() {
    if (!fresh) return
    try {
      await navigator.clipboard.writeText(fresh.token)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">MCP tokens</CardTitle>
        <p className="text-xs text-muted-foreground">
          Bearer tokens for the Helm MCP server and for pipelines that pull the keyword queue. A read token can only read; a write token can also
          queue inspections, run the generator and decide keywords. Tokens are stored hashed and shown once.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {fresh && (
          <div className="flex flex-col gap-2 rounded-md border border-border bg-muted p-3 text-sm" role="status">
            <p>
              Token for <strong>{fresh.label}</strong>. Copy it now; it will not be shown again.
            </p>
            <code className="break-all rounded bg-background p-2 text-xs">{fresh.token}</code>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={copy}>
                <Copy size={14} /> {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setFresh(null)}>
                Done
              </Button>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2">
          <Field label="Label">
            <Input placeholder="e.g. claude-code" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={100} />
          </Field>
          <Field label="Scope">
            <Select value={scope} onChange={(e) => setScope(e.target.value as 'read' | 'write')}>
              <option value="read">read</option>
              <option value="write">write</option>
            </Select>
          </Field>
          <Button size="sm" disabled={!label.trim()} onClick={create}>
            Create token
          </Button>
        </div>
        {message && <p className="text-sm text-destructive">{message}</p>}

        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-card text-left text-muted-foreground">
              <tr>
                {['Label', 'Scope', 'Created', 'Last used', ''].map((h, i) => (
                  <th key={`${h}-${i}`} className="px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tokens?.map((t) => (
                <tr key={t.id} className="border-t border-border">
                  <td className="px-3 py-1.5">{t.label}</td>
                  <td className="px-3 py-1.5">
                    <Badge variant={t.scope === 'write' ? 'yellow' : 'muted'}>{t.scope}</Badge>
                  </td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{formatDateTime(t.created_at)}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">{formatDateTime(t.last_used_at)}</td>
                  <td className="px-3 py-1.5">
                    {t.revoked_at ? (
                      <Badge variant="red">revoked</Badge>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => revoke(t.id)}>
                        Revoke
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
              {tokens && tokens.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                    No tokens yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

export function SettingsPage() {
  const { isDemo } = useAuth()
  const [data, setData] = React.useState<SettingsData | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    fetchSettings()
      .then(setData)
      .catch(() => setError('Failed to load settings.'))
    fetchProjects()
      .then((all) => setProjects(all.filter((p) => p.is_pipeline)))
      .catch(() => undefined)
  }, [])

  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Settings</h1>
      {!data.editable && <p className="text-sm text-muted-foreground">The demo account can look but not change anything.</p>}
      <IndexingSettings data={data} projects={projects} editable={data.editable} />
      <KeywordSettings data={data} editable={data.editable} />
      {!isDemo && <McpTokens />}
    </div>
  )
}
