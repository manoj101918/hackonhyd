import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type CurvePoint, type Learned } from '../api'
import { useApp } from '../state'
import { Card, FactBadge, fmtDate, IncidentChip, SectionTitle, Spinner } from './ui'

// Validated categorical slots (dark surface, all-pairs) + distinct marker shapes as secondary encoding.
const GROUPS = [
  { key: 'before', label: 'Before Déjà Vu', color: 'var(--color-series-3)', shape: 'circle' as const },
  { key: 'assisted', label: 'With Déjà Vu', color: 'var(--color-series-1)', shape: 'square' as const },
  { key: 'live', label: 'Live demo runs', color: 'var(--color-series-2)', shape: 'diamond' as const },
]
type GroupKey = 'before' | 'assisted' | 'live'
const groupOf = (p: CurvePoint): GroupKey => (p.source === 'live' ? 'live' : p.assisted ? 'assisted' : 'before')

interface Row extends CurvePoint { t: number; group: GroupKey; avg?: number }

export function Learning() {
  const { incidents } = useApp()
  const [points, setPoints] = useState<CurvePoint[] | null>(null)
  const [learned, setLearned] = useState<Learned | null>(null)
  const [showTable, setShowTable] = useState(false)

  const resolvedCount = incidents.filter((i) => i.status === 'resolved').length
  useEffect(() => { api.learningCurve().then(setPoints).catch(() => setPoints([])) }, [resolvedCount])
  useEffect(() => { api.learned().then(setLearned).catch(() => setLearned(null)) }, [resolvedCount])

  const rows: Row[] = (points ?? [])
    .map((p) => ({ ...p, t: Date.parse(p.date), group: groupOf(p) }))
    .sort((a, b) => a.t - b.t)
  rows.forEach((r, i) => {
    const window = rows.slice(Math.max(0, i - 3), i + 1)
    r.avg = Math.round(window.reduce((s, x) => s + x.ttr_minutes, 0) / window.length)
  })
  const mean = (g: GroupKey) => {
    const xs = rows.filter((r) => r.group === g).map((r) => r.ttr_minutes)
    return xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : null
  }
  const before = mean('before'), assisted = mean('assisted'), live = mean('live')
  const adoption = rows.find((r) => r.group === 'assisted')?.t

  return (
    <div className="h-full space-y-6 overflow-y-auto px-6 py-5">
      <div>
        <h2 className="text-lg font-semibold text-ink">Learning curve</h2>
        <p className="mt-0.5 text-sm text-ink-2">Time to resolve every incident at Acme over the last 90 days — and the ones you just resolved live.</p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <StatTile label="MTTR before Déjà Vu" value={before} sub={`${rows.filter((r) => r.group === 'before').length} incidents`} />
        <StatTile label="MTTR with Déjà Vu" value={assisted} sub={before && assisted ? `${Math.round((1 - assisted / before) * 100)}% faster` : ''} accent />
        <StatTile label="Live demo runs" value={live} sub={live === null ? 'resolve a scenario to add one' : `${rows.filter((r) => r.group === 'live').length} resolved (demo clock ×10)`} />
      </div>

      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-center gap-4 text-xs text-ink-2">
          <span className="font-medium text-ink">Time to resolve (minutes)</span>
          {GROUPS.map((g) => (
            <span key={g.key} className="flex items-center gap-1.5"><LegendMark shape={g.shape} color={g.color} />{g.label}</span>
          ))}
          <span className="flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-ink-3" />4-incident rolling average</span>
          <button onClick={() => setShowTable((v) => !v)} className="ml-auto text-ink-3 underline-offset-2 hover:text-ink hover:underline">
            {showTable ? 'Show chart' : 'Show table'}
          </button>
        </div>
        {points === null ? <div className="flex h-72 items-center justify-center"><Spinner className="text-ink-3" /></div> : showTable ? (
          <CurveTable rows={rows} />
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={rows} margin={{ top: 16, right: 16, bottom: 4, left: -8 }}>
                <CartesianGrid stroke="var(--color-line)" strokeDasharray="0" vertical={false} />
                <XAxis dataKey="t" type="number" scale="time" domain={['dataMin - 86400000', 'dataMax + 86400000']}
                  tickFormatter={(t) => fmtDate(new Date(t).toISOString())} stroke="var(--color-ink-3)" tick={{ fontSize: 11 }} tickLine={false} axisLine={{ stroke: 'var(--color-line)' }} />
                <YAxis stroke="var(--color-ink-3)" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
                <Tooltip content={<CurveTooltip />} cursor={{ stroke: 'var(--color-ink-3)', strokeDasharray: '3 3' }} />
                {adoption && (
                  <ReferenceLine x={adoption - 12 * 3600e3} stroke="var(--color-memory)" strokeDasharray="4 4"
                    label={{ value: 'Déjà Vu joins on-call', fill: 'var(--color-memory)', fontSize: 11, position: 'insideTopRight' }} />
                )}
                <Line dataKey="avg" type="monotone" stroke="var(--color-ink-3)" strokeWidth={2} dot={false} isAnimationActive={false} />
                {GROUPS.map((g) => (
                  <Scatter key={g.key} data={rows.filter((r) => r.group === g.key)} dataKey="ttr_minutes" fill={g.color}
                    shape={g.shape} stroke="var(--color-surface)" strokeWidth={2} isAnimationActive={false} />
                ))}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <SectionTitle>What Déjà Vu has learned</SectionTitle>
          <p className="-mt-1 mb-3 text-xs text-ink-3">Observations Hindsight consolidated on its own from individual facts — patterns no single incident states.</p>
          {!learned ? <Spinner className="text-ink-3" /> : !learned.available ? (
            <div className="text-xs text-bad">Memory unavailable: {learned.reason}</div>
          ) : (
            <div className="space-y-4">
              {learned.groups.map((g) => (
                <div key={g.title}>
                  <div className="mb-1.5 text-sm font-medium text-ink">{g.title}</div>
                  <ul className="space-y-1.5">
                    {g.observations.slice(0, 4).map((o) => (
                      <li key={o.id} className="rounded-lg border border-line bg-surface px-3 py-2">
                        <div className="mb-1 flex flex-wrap items-center gap-1"><FactBadge type={o.type} />{o.incident_ids.map((id) => <IncidentChip key={id} id={id} />)}</div>
                        <p className="text-xs leading-relaxed text-ink-2">{o.text}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <SectionTitle right={learned?.playbook?.updated_at ? <span className="text-[10px] text-ink-3">refreshed {new Date(learned.playbook.updated_at).toLocaleString()}</span> : null}>
            Remediation playbook (mental model)
          </SectionTitle>
          <p className="-mt-1 mb-3 text-xs text-ink-3">A Hindsight mental model that re-writes itself after every memory consolidation.</p>
          <Card className="markdown px-4 py-2">
            {learned?.playbook?.content ? <Markdown>{learned.playbook.content}</Markdown>
              : <div className="py-3 text-xs text-ink-3">{learned ? 'The playbook is still being generated — check back in a minute.' : <Spinner />}</div>}
          </Card>
        </div>
      </div>
    </div>
  )
}

function StatTile({ label, value, sub, accent }: { label: string; value: number | null; sub: string; accent?: boolean }) {
  return (
    <Card className={accent ? 'border-memory/40 px-4 py-3' : 'px-4 py-3'}>
      <div className="text-[11px] uppercase tracking-wider text-ink-3">{label}</div>
      <div className="mt-1 font-mono text-3xl font-semibold text-ink">{value ?? '–'}<span className="ml-1 text-sm font-normal text-ink-3">{value !== null && 'min'}</span></div>
      <div className={accent ? 'text-xs text-memory' : 'text-xs text-ink-3'}>{sub}</div>
    </Card>
  )
}

function LegendMark({ shape, color }: { shape: string; color: string }) {
  if (shape === 'square') return <span className="inline-block h-2.5 w-2.5 rounded-[2px]" style={{ background: color }} />
  if (shape === 'diamond') return <span className="inline-block h-2.5 w-2.5 rotate-45 rounded-[1px]" style={{ background: color }} />
  return <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
}

function CurveTooltip({ active, payload }: { active?: boolean; payload?: { payload: Row }[] }) {
  const row = payload?.find((p) => p.payload?.id)?.payload
  if (!active || !row) return null
  const g = GROUPS.find((x) => x.key === row.group)!
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs shadow-xl">
      <div className="flex items-center gap-1.5"><LegendMark shape={g.shape} color={g.color} /><span className="font-mono text-ink">{row.id}</span><span className="text-ink-3">{fmtDate(row.date)}</span></div>
      <div className="mt-1 max-w-64 text-ink-2">{row.title}</div>
      <div className="mt-1 text-ink"><span className="font-mono text-base">{row.ttr_minutes}</span> min to resolve <span className="text-ink-3">· {row.service} · {row.severity}</span></div>
    </div>
  )
}

function CurveTable({ rows }: { rows: Row[] }) {
  return (
    <div className="max-h-72 overflow-y-auto">
      <table className="w-full text-left text-xs">
        <thead className="sticky top-0 bg-surface text-ink-3"><tr><th className="py-1">Incident</th><th>Date</th><th>Service</th><th>Group</th><th className="text-right">TTR (min)</th></tr></thead>
        <tbody className="text-ink-2">
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-line">
              <td className="py-1 font-mono text-ink">{r.id}</td><td>{fmtDate(r.date)}</td><td>{r.service}</td>
              <td>{GROUPS.find((g) => g.key === r.group)!.label}</td><td className="text-right font-mono">{r.ttr_minutes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
