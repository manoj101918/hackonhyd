import { useMemo, useState } from 'react'
import { api, type MemoryHit } from '../api'
import { runKey, useApp } from '../state'
import { cx, FactBadge, fmtDate, Icon, IncidentChip, Spinner } from './ui'

type Filter = 'all' | 'observation' | 'experience' | 'world'

/** The star of the show: every memory the agent is looking at, as it arrives. */
export function MemoryPanel() {
  const { tab, active, memoryOn, runs, deploy, counts } = useApp()
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState<{ q: string; hits: MemoryHit[]; loading: boolean } | null>(null)

  const source = useMemo(() => {
    if (tab === 'deploy') {
      const r = deploy.result
      return {
        title: 'Evidence for deploy check',
        memories: r?.memories ?? [],
        cited: new Set(r?.risk.evidence_incident_ids ?? []),
        loading: deploy.status === 'running',
        off: r?.memory_mode === 'off',
      }
    }
    if (!active) return null
    const mode = tab === 'compare' || memoryOn ? 'on' : 'off'
    const run = runs[runKey(active.id, mode)]
    const streamed = (run?.events ?? []).flatMap((e) => (e.type === 'tool_result' ? e.memories : []))
    const memories = run?.result?.memories ?? dedupe(streamed)
    const a = run?.result?.analysis
    const cited = new Set([
      ...(a?.similar_incidents.map((s) => s.id) ?? []),
      ...(a?.recommended_steps.flatMap((s) => s.evidence_incident_ids) ?? []),
      ...(a?.avoid_steps.flatMap((s) => s.evidence_incident_ids) ?? []),
    ])
    return { title: `Recalled for ${active.id}`, memories, cited, loading: run?.status === 'running', off: mode === 'off' }
  }, [tab, active, memoryOn, runs, deploy])

  const shown = search ? search.hits : source?.memories ?? []
  const cited = search ? new Set<string>() : source?.cited ?? new Set<string>()
  const byType = (t: Filter) => (t === 'all' ? shown : shown.filter((m) => m.type === t))
  const list = [...byType(filter)].sort((a, b) => Number(isCited(b, cited)) - Number(isCited(a, cited)))

  const runSearch = async () => {
    if (!query.trim()) { setSearch(null); return }
    setSearch({ q: query, hits: [], loading: true })
    try {
      const res = await api.search(query)
      setSearch({ q: query, hits: res.memories, loading: false })
    } catch {
      setSearch({ q: query, hits: [], loading: false })
    }
  }

  return (
    <aside className="flex h-full min-h-0 flex-col overflow-hidden border-l border-line bg-surface/60">
      <div className="border-b border-line px-4 pb-3 pt-3.5">
        <div className="flex items-center gap-2">
          <span className="text-memory">{Icon.brain('h-4 w-4')}</span>
          <h2 className="text-sm font-semibold text-ink">Memory</h2>
          <span className="ml-auto font-mono text-[10px] text-ink-3">
            {counts.world ?? '–'} world · {counts.experience ?? '–'} exp · {counts.observation ?? '–'} obs
          </span>
        </div>
        <form className="mt-2.5 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); runSearch() }}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ask memory… e.g. what failed for redis?"
            className="min-w-0 flex-1 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-3 focus:border-memory/60 focus:outline-none" />
          {search && <button type="button" onClick={() => { setSearch(null); setQuery('') }} className="px-1 text-xs text-ink-3 hover:text-ink">clear</button>}
        </form>
      </div>

      <div className="flex items-center gap-1 border-b border-line px-3 py-2">
        {(['all', 'observation', 'experience', 'world'] as Filter[]).map((f) => (
          <button key={f} onClick={() => setFilter(f)}
            className={cx('rounded-md px-2 py-1 text-[11px] capitalize transition', filter === f ? 'bg-surface-3 text-ink' : 'text-ink-3 hover:text-ink-2')}>
            {f} <span className="font-mono text-ink-3">{byType(f).length}</span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="mb-2 flex items-center gap-2 px-1 text-[11px] text-ink-3">
          {search ? <>Search: “{search.q}”</> : source?.title ?? 'Nothing recalled yet'}
          {(search?.loading || source?.loading) && <Spinner className="text-memory" />}
        </div>
        {!search && source?.off && (
          <div className="rounded-lg border border-dashed border-line px-3 py-6 text-center text-xs text-ink-3">
            Memory is <span className="text-ink-2">OFF</span>. The agent is working without any history —<br />flip the toggle to see what it would remember.
          </div>
        )}
        {!search && !source && (
          <div className="px-1 text-xs text-ink-3">Play a scenario: memories the agent recalls will stream in here, with where they came from.</div>
        )}
        {!source?.off && list.length === 0 && !source?.loading && source && !search && (
          <div className="px-1 text-xs text-ink-3">No similar past incidents found.</div>
        )}
        <ul className="space-y-2">
          {list.slice(0, 60).map((m) => <MemoryCard key={m.id} m={m} cited={isCited(m, cited)} citedIds={cited} />)}
        </ul>
      </div>
    </aside>
  )
}

function MemoryCard({ m, cited, citedIds }: { m: MemoryHit; cited: boolean; citedIds: Set<string> }) {
  return (
    <li className={cx('slide-in rounded-lg border px-3 py-2', cited ? 'border-memory/50 bg-memory/8' : 'border-line bg-surface-2/50')}>
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <FactBadge type={m.type} />
        {m.incident_ids.slice(0, 4).map((id) => <IncidentChip key={id} id={id} highlight={citedIds.has(id)} />)}
        {m.incident_ids.length > 4 && <span className="text-[10px] text-ink-3">+{m.incident_ids.length - 4}</span>}
        <span className="ml-auto text-[10px] text-ink-3">{fmtDate(m.date)}</span>
      </div>
      <p className="text-xs leading-relaxed text-ink-2">{m.text}</p>
      {cited && <div className="mt-1 text-[10px] font-medium uppercase tracking-wider text-memory">cited as evidence</div>}
    </li>
  )
}

function isCited(m: MemoryHit, cited: Set<string>) {
  return m.incident_ids.some((id) => cited.has(id))
}

function dedupe(hits: MemoryHit[]) {
  const seen = new Set<string>()
  return hits.filter((h) => (seen.has(h.id) ? false : (seen.add(h.id), true)))
}
