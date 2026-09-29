import { useState } from 'react'
import type { AgentEvent, AnalysisResult, LiveIncident, Outcome } from '../api'
import type { Run } from '../state'
import { Button, cx, fmtDate, Icon, IncidentChip, Spinner, TOOL_META } from './ui'

/** Streaming view of what the agent is doing: each tool call, and what came back. */
export function RunTimeline({ run, compact }: { run: Run; compact?: boolean }) {
  const results = new Map(run.events.filter((e) => e.type === 'tool_result').map((e) => [(e as { id: string }).id, e]))
  const rows = run.events.filter((e) => e.type !== 'tool_result' && e.type !== 'final')
  return (
    <ol className="space-y-1">
      {rows.map((e, i) => <TimelineRow key={i} event={e} result={e.type === 'tool_call' ? results.get(e.id) : undefined} compact={compact} running={run.status === 'running'} />)}
      {run.status === 'running' && !rows.some((e) => e.type === 'status' && e.message === 'Writing analysis') && rows.length > 0 && (
        <li className="flex items-center gap-2 pl-1 text-xs text-ink-3"><Spinner /> thinking…</li>
      )}
      {run.status === 'running' && rows.some((e) => e.type === 'status' && e.message === 'Writing analysis') && (
        <li className="flex items-center gap-2 pl-1 text-xs text-ink-3"><Spinner /> writing analysis…</li>
      )}
    </ol>
  )
}

function TimelineRow({ event, result, compact, running }: { event: AgentEvent; result?: AgentEvent; compact?: boolean; running: boolean }) {
  if (event.type === 'status') {
    if (event.message === 'Writing analysis') return null
    return <li className="pl-1 text-xs text-ink-3">{event.message}</li>
  }
  if (event.type === 'retry') {
    return <li className="pl-1 text-xs text-warn">↻ retried {event.retries}× (rate limit / malformed output) → {event.model}</li>
  }
  if (event.type === 'degraded') {
    return <li className="pl-1 text-xs text-warn">⚠ language model unavailable — answering from memory alone</li>
  }
  if (event.type === 'memory_unavailable') {
    return <li className="pl-1 text-xs text-bad">⚠ memory unreachable ({event.reason}) — continuing without memory</li>
  }
  if (event.type === 'error') return <li className="pl-1 text-xs text-bad">Error: {event.message}</li>
  if (event.type !== 'tool_call') return null
  const meta = TOOL_META[event.name] ?? { label: event.name, memory: false, icon: Icon.spark }
  const arg = String(event.args.symptoms ?? event.args.question ?? event.args.change_description ?? event.args.service ?? '')
  const summary = result && result.type === 'tool_result' ? result.summary : null
  return (
    <li className={cx('slide-in flex items-start gap-2 rounded-md px-2 py-1 text-xs', meta.memory ? 'bg-memory/8 text-ink' : 'text-ink-2')}>
      <span className={cx('mt-px shrink-0', meta.memory ? 'text-memory' : 'text-ink-3')}>{meta.icon('h-3.5 w-3.5')}</span>
      <span className="min-w-0 flex-1">
        <span className="font-medium">{meta.label}</span>
        {!compact && arg && <span className="ml-1.5 text-ink-3">“{arg.length > 90 ? arg.slice(0, 90) + '…' : arg}”</span>}
        {summary ? <span className={cx('ml-1.5', meta.memory ? 'text-memory' : 'text-ink-2')}>→ {summary}</span>
          : running && <Spinner className="ml-2 align-[-2px] text-ink-3" />}
      </span>
    </li>
  )
}

const CONF = { high: 'text-good border-good/40 bg-good/10', medium: 'text-warn border-warn/40 bg-warn/10', low: 'text-ink-2 border-line bg-surface-3' }

interface StepActions {
  incident: LiveIncident
  onMark: (step: string, outcome: Outcome) => Promise<unknown>
}

export function AnalysisCard({ result, actions, compact }: { result: AnalysisResult; actions?: StepActions; compact?: boolean }) {
  const { analysis: a, meta } = result
  const memoryIds = new Set(result.memories.flatMap((m) => m.incident_ids))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={cx('rounded border px-1.5 py-px font-medium uppercase tracking-wide', CONF[a.confidence])}>{a.confidence} confidence</span>
        {meta.memory_mode === 'on' && meta.history_found && (
          <span className="rounded border border-memory/40 bg-memory/10 px-1.5 py-px text-memory">{memoryIds.size} past incidents in memory context</span>
        )}
        <span className="text-ink-3">{meta.model?.replace('openai/', '')} · {(meta.elapsed_ms / 1000).toFixed(1)}s{meta.retries ? ` · ${meta.retries} retr${meta.retries > 1 ? 'ies' : 'y'}` : ''}</span>
      </div>

      {meta.degraded && (
        <div className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
          Degraded answer: the language model was unavailable, so this is built from memory alone. ({meta.degraded_reason?.slice(0, 140)})
        </div>
      )}

      <p className="text-sm leading-relaxed text-ink">{a.summary}</p>
      <div className="rounded-lg border border-line bg-surface-2 px-3 py-2">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Likely root cause</div>
        <div className="mt-0.5 text-sm text-ink">{a.likely_root_cause}</div>
      </div>

      <div>
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Recommended steps</div>
        <ol className="space-y-2">
          {a.recommended_steps.map((s, i) => (
            <li key={i} className="rounded-lg border border-line bg-surface-2/60 px-3 py-2">
              <div className="flex gap-2">
                <span className="mt-px font-mono text-xs text-ink-3">{i + 1}.</span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-ink">{s.step}</div>
                  {!compact && s.rationale && <div className="mt-0.5 text-xs text-ink-2">{s.rationale}</div>}
                  <Evidence ids={s.evidence_incident_ids} label="proven in" />
                </div>
              </div>
              {actions && <StepButtons step={s.step} {...actions} />}
            </li>
          ))}
        </ol>
      </div>

      {a.avoid_steps.length > 0 && (
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-bad/80">Don't do this — it failed before</div>
          <ul className="space-y-2">
            {a.avoid_steps.map((s, i) => (
              <li key={i} className="flex gap-2 rounded-lg border border-bad/30 bg-bad/5 px-3 py-2">
                <span className="mt-0.5 text-bad">{Icon.x('h-3.5 w-3.5')}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-ink">{s.step}</div>
                  {!compact && s.reason && <div className="mt-0.5 text-xs text-ink-2">{s.reason}</div>}
                  <Evidence ids={s.evidence_incident_ids} label="failed in" />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Similar past incidents</div>
        {a.similar_incidents.length === 0 ? (
          <div className="text-xs text-ink-3">
            {meta.memory_mode === 'off' ? 'Memory is off — the agent cannot see past incidents.' : 'No similar past incidents found.'}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {a.similar_incidents.map((s) => (
              <li key={s.id} className="flex items-start gap-2 text-xs">
                <IncidentChip id={s.id} />
                <span className="shrink-0 text-ink-3">{fmtDate(s.date)}</span>
                <span className="text-ink-2">{s.similarity_reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {meta.stripped_citations.length > 0 && (
        <div className="text-[11px] text-ink-3" title="Citations the memory never returned are removed before display">
          Grounding check removed {meta.stripped_citations.length} unbacked citation{meta.stripped_citations.length > 1 ? 's' : ''} ({meta.stripped_citations.join(', ')}).
        </div>
      )}
    </div>
  )
}

function Evidence({ ids, label }: { ids: string[]; label: string }) {
  if (!ids.length) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1 text-[11px] text-ink-3">
      <span>{label}</span>
      {ids.map((id) => <IncidentChip key={id} id={id} />)}
    </div>
  )
}

function StepButtons({ step, incident, onMark }: { step: string } & StepActions) {
  const [busy, setBusy] = useState<Outcome | null>(null)
  const done = incident.steps.find((s) => s.step === step)
  if (done) {
    return (
      <div className={cx('mt-2 flex items-center gap-1.5 text-xs', done.outcome === 'WORKED' ? 'text-good' : 'text-bad')}>
        {done.outcome === 'WORKED' ? Icon.check('h-3.5 w-3.5') : Icon.x('h-3.5 w-3.5')}
        Marked {done.outcome.toLowerCase()}
        {done.retained && <span className="ml-1 inline-flex items-center gap-1 text-memory">{Icon.save('h-3.5 w-3.5')} retained to memory</span>}
      </div>
    )
  }
  if (incident.status === 'resolved') return null
  const mark = async (o: Outcome) => { setBusy(o); try { await onMark(step, o) } finally { setBusy(null) } }
  return (
    <div className="mt-2 flex gap-2">
      <Button variant="good" className="!px-2 !py-1 !text-xs" disabled={!!busy} onClick={() => mark('WORKED')}>
        {busy === 'WORKED' ? <Spinner /> : Icon.check('h-3.5 w-3.5')} Mark worked
      </Button>
      <Button variant="bad" className="!px-2 !py-1 !text-xs" disabled={!!busy} onClick={() => mark('FAILED')}>
        {busy === 'FAILED' ? <Spinner /> : Icon.x('h-3.5 w-3.5')} Mark failed
      </Button>
    </div>
  )
}
