import { useState } from 'react'
import type { Scenario } from '../api'
import { fmtClock, simMinutes, useApp, type Tab } from '../state'
import { Button, cx, Dot, Icon, Spinner } from './ui'

const TABS: { key: Tab; label: string }[] = [
  { key: 'channel', label: 'Incident channel' },
  { key: 'compare', label: 'Compare ON vs OFF' },
  { key: 'deploy', label: 'Deploy check' },
  { key: 'learning', label: 'Learning' },
]

export function TopBar() {
  const { tab, setTab, memoryOn, setMemoryOn, health } = useApp()
  return (
    <header className="flex items-center gap-6 border-b border-line bg-surface px-5 py-2.5">
      <div className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-memory/15 text-memory">{Icon.brain('h-5 w-5')}</div>
        <div className="leading-tight">
          <div className="text-[15px] font-semibold tracking-tight text-ink">Déjà Vu</div>
          <div className="text-[11px] text-ink-3">incident memory · Acme Commerce</div>
        </div>
      </div>
      <nav className="flex gap-1">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={cx('rounded-lg px-3 py-1.5 text-sm transition', tab === t.key ? 'bg-surface-3 text-ink' : 'text-ink-2 hover:text-ink')}>
            {t.label}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-5">
        <div className="flex items-center gap-3 text-[11px] text-ink-3">
          <span className="flex items-center gap-1.5" title={health?.memory.reason ?? health?.memory.base_url}><Dot ok={health ? health.memory.available : null} />Hindsight</span>
          <span className="flex items-center gap-1.5" title={health?.llm.models.join(' → ')}><Dot ok={health ? health.llm.configured : null} />Groq</span>
        </div>
        <MemoryToggle on={memoryOn} onChange={setMemoryOn} />
      </div>
    </header>
  )
}

function MemoryToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button role="switch" aria-checked={on} onClick={() => onChange(!on)}
      className={cx('flex items-center gap-2.5 rounded-full border py-1 pl-3 pr-1 text-sm font-medium transition',
        on ? 'border-memory/60 bg-memory/15 text-ink' : 'border-line bg-surface-2 text-ink-2')}>
      Memory {on ? 'ON' : 'OFF'}
      <span className={cx('relative h-6 w-11 rounded-full transition', on ? 'bg-memory' : 'bg-surface-3')}>
        <span className={cx('absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all', on ? 'left-[22px]' : 'left-0.5')} />
      </span>
    </button>
  )
}

export function MemoryBanner() {
  const { health, memoryOn } = useApp()
  if (!health || health.memory.available || !memoryOn) return null
  return (
    <div className="border-b border-bad/40 bg-bad/10 px-5 py-2 text-sm text-bad">
      ⚠ Hindsight memory is unreachable ({health.memory.reason}). Déjà Vu is running in <b>no-memory mode</b> — answers will be generic.
    </div>
  )
}

export function DemoBar() {
  const { scenarios, playScenario, resetDemo, active, now, incidents } = useApp()
  const [busy, setBusy] = useState<string | null>(null)
  const play = async (s: Scenario) => { setBusy(s.id); try { await playScenario(s) } finally { setBusy(null) } }
  const open = incidents.filter((i) => i.status === 'open')
  return (
    <div className="flex items-center gap-2 border-b border-line bg-bg px-5 py-2">
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Demo</span>
      {scenarios.map((s, i) => (
        <Button key={s.id} variant="default" className="!py-1 !text-xs" disabled={!!busy} onClick={() => play(s)} title={s.title}>
          {busy === s.id ? <Spinner /> : Icon.play()} {i + 1} · {shortTitle(s)}
        </Button>
      ))}
      <div className="ml-auto flex items-center gap-4 text-xs text-ink-3">
        {active && active.status === 'open' && (
          <span className="flex items-center gap-2" title="Simulated clock: 1 real second = 10 simulated seconds">
            <span className="pulse-memory h-2 w-2 rounded-full bg-bad" />
            {active.id} open · MTTR <span className="font-mono text-sm text-ink tabular-nums">{fmtClock(simMinutes(active.started_at, now))}</span>
            <span className="text-[10px]">(demo clock ×10)</span>
          </span>
        )}
        {open.length > 1 && <span>{open.length} open incidents</span>}
        <Button variant="ghost" className="!py-1 !text-xs" onClick={() => { if (confirm('Clear live demo incidents? (Memory is kept.)')) resetDemo() }}>Reset demo</Button>
      </div>
    </div>
  )
}

function shortTitle(s: Scenario) {
  if (s.kind === 'deploy_check') return `Deploy check: ${s.service}`
  return `${s.service} · ${s.id.includes('500') ? 'HTTP 500s' : 'DB errors'}`
}
