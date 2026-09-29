import { useEffect } from 'react'
import type { AnalysisResult } from '../api'
import { runKey, useApp, type Mode } from '../state'
import { AnalysisCard, RunTimeline } from './Analysis'
import { Button, Card, cx, Icon, SevBadge, Spinner } from './ui'

/** Same alert, same tools, same model — the only difference is long-term memory. */
export function Compare() {
  const { active, runs, analyze, scenarios, playScenario } = useApp()

  useEffect(() => {
    if (!active) return
    for (const mode of ['off', 'on'] as Mode[]) if (!runs[runKey(active.id, mode)]) analyze(active.id, mode)
  }, [active, runs, analyze])

  if (!active) {
    const first = scenarios.find((s) => s.kind === 'incident')
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-ink-2">Pick an incident to compare the agent with and without memory.</p>
          {first && <Button variant="primary" className="mt-3" onClick={() => playScenario(first)}>{Icon.play()} Play “{first.title}”</Button>}
        </div>
      </div>
    )
  }

  const off = runs[runKey(active.id, 'off')]
  const on = runs[runKey(active.id, 'on')]
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-line px-5 py-3">
        <SevBadge sev={active.severity} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">{active.id} · {active.alert}</div>
          <div className="text-xs text-ink-3">Same alert, same tools, same model. The only difference is long-term memory.</div>
        </div>
        <Button variant="ghost" className="!text-xs" onClick={() => { analyze(active.id, 'off'); analyze(active.id, 'on') }}>↻ Run both again</Button>
      </div>
      {off?.result && on?.result && <Scoreboard off={off.result} on={on.result} />}
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-4 overflow-hidden px-5 py-4">
        {(['off', 'on'] as Mode[]).map((mode) => {
          const run = mode === 'off' ? off : on
          return (
            <Card key={mode} className={cx('flex min-h-0 flex-col', mode === 'on' && 'border-memory/40')}>
              <div className={cx('flex items-center gap-2 border-b px-4 py-2.5', mode === 'on' ? 'border-memory/30' : 'border-line')}>
                <span className={mode === 'on' ? 'text-memory' : 'text-ink-3'}>{Icon.brain('h-4 w-4')}</span>
                <span className="text-sm font-semibold text-ink">Memory {mode.toUpperCase()}</span>
                <span className="text-xs text-ink-3">{mode === 'on' ? 'recalls 90 days of incidents via Hindsight' : 'logs + deploys + general knowledge only'}</span>
                {run?.status === 'running' && <Spinner className="ml-auto text-ink-3" />}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
                {run && <RunTimeline run={run} compact />}
                {run?.result && <div className="mt-3 border-t border-line pt-3"><AnalysisCard result={run.result} compact /></div>}
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

function Scoreboard({ off, on }: { off: AnalysisResult; on: AnalysisResult }) {
  const stats = (r: AnalysisResult) => {
    const a = r.analysis
    const cited = new Set([...a.similar_incidents.map((s) => s.id), ...a.recommended_steps.flatMap((s) => s.evidence_incident_ids), ...a.avoid_steps.flatMap((s) => s.evidence_incident_ids)])
    return {
      cited: cited.size,
      backed: a.recommended_steps.filter((s) => s.evidence_incident_ids.length).length,
      total: a.recommended_steps.length,
      warned: a.avoid_steps.filter((s) => s.evidence_incident_ids.length).length,
      confidence: a.confidence,
    }
  }
  const [o, n] = [stats(off), stats(on)]
  const rows: [string, string, string][] = [
    ['Past incidents cited', String(o.cited), String(n.cited)],
    ['Steps backed by evidence', `${o.backed}/${o.total}`, `${n.backed}/${n.total}`],
    ['Known-bad fixes flagged', String(o.warned), String(n.warned)],
    ['Confidence', o.confidence, n.confidence],
  ]
  return (
    <div className="grid grid-cols-4 gap-3 border-b border-line px-5 py-3">
      {rows.map(([label, a, b]) => (
        <div key={label} className="rounded-lg border border-line bg-surface px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-ink-3">{label}</div>
          <div className="mt-0.5 flex items-baseline gap-2 font-mono">
            <span className="text-sm text-ink-3">{a}</span>
            <span className="text-xs text-ink-3">→</span>
            <span className="text-lg font-semibold text-memory">{b}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
