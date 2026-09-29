import { useEffect, useState, type ReactNode } from 'react'
import type { LiveIncident } from '../api'
import { fmtClock, runKey, simMinutes, useApp, type FeedItem, type Mode } from '../state'
import { AnalysisCard, RunTimeline } from './Analysis'
import { Button, Card, cx, Icon, SevBadge, Spinner } from './ui'

export function IncidentChannel() {
  const { active, memoryOn, runs, analyze } = useApp()
  const mode: Mode = memoryOn ? 'on' : 'off'
  const run = active ? runs[runKey(active.id, mode)] : undefined

  // Every new alert (and every memory toggle) gets an analysis automatically.
  useEffect(() => {
    if (active && active.status === 'open' && !run) analyze(active.id, mode)
  }, [active, run, mode, analyze])

  if (!active) return <EmptyChannel />
  return (
    <div className="flex h-full flex-col">
      <ChannelHeader incident={active} />
      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        <AlertMessage incident={active} />
        <AgentMessage incident={active} mode={mode} />
        <Feed incident={active} />
      </div>
      <ResolveBar incident={active} mode={mode} />
    </div>
  )
}

function ChannelHeader({ incident }: { incident: LiveIncident }) {
  const { incidents, setActiveId, now, analyze, memoryOn } = useApp()
  const minutes = incident.status === 'resolved' ? incident.ttr_minutes ?? 0 : simMinutes(incident.started_at, now)
  return (
    <div className="flex items-center gap-3 border-b border-line px-5 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-ink">#{incident.id.toLowerCase()}-{incident.service}</span>
          <SevBadge sev={incident.severity} />
          <span className={cx('rounded px-1.5 py-px text-[11px] font-medium', incident.status === 'open' ? 'bg-bad/15 text-bad' : 'bg-good/15 text-good')}>
            {incident.status === 'open' ? '● open' : '✓ resolved'}
          </span>
        </div>
        <div className="truncate text-xs text-ink-3">{incident.title}</div>
      </div>
      <div className="text-right" title="Demo clock runs 10× faster than real time">
        <div className="text-[10px] uppercase tracking-wider text-ink-3">{incident.status === 'open' ? 'time to resolve' : 'resolved in'}</div>
        <div className={cx('font-mono text-lg tabular-nums', incident.status === 'open' ? 'text-ink' : 'text-good')}>
          {incident.status === 'open' ? fmtClock(minutes) : `${minutes} min`}
        </div>
      </div>
      {incidents.length > 1 && (
        <select value={incident.id} onChange={(e) => setActiveId(e.target.value)}
          className="rounded-lg border border-line bg-surface-2 px-2 py-1.5 text-xs text-ink">
          {incidents.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.service}{i.status === 'resolved' ? ' ✓' : ''}</option>)}
        </select>
      )}
      <Button variant="ghost" className="!text-xs" onClick={() => analyze(incident.id, memoryOn ? 'on' : 'off')}>↻ Re-analyze</Button>
    </div>
  )
}

function Avatar({ kind }: { kind: 'alert' | 'agent' | 'human' }) {
  const s = {
    alert: ['bg-bad/20 text-bad', Icon.alert('h-4 w-4')],
    agent: ['bg-memory/20 text-memory', Icon.brain('h-4 w-4')],
    human: ['bg-surface-3 text-ink-2', <span className="text-xs font-semibold">You</span>],
  }[kind]
  return <div className={cx('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg', s[0] as string)}>{s[1]}</div>
}

function Message({ kind, name, meta, children }: { kind: 'alert' | 'agent' | 'human'; name: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <div className="slide-in flex gap-3">
      <Avatar kind={kind} />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2 text-sm">
          <span className="font-semibold text-ink">{name}</span>
          {meta}
        </div>
        {children}
      </div>
    </div>
  )
}

function AlertMessage({ incident }: { incident: LiveIncident }) {
  return (
    <Message kind="alert" name="Alertmanager" meta={<span className="text-xs text-ink-3">{new Date(incident.started_at).toLocaleTimeString()}</span>}>
      <Card className="border-l-2 border-l-bad px-4 py-3">
        <div className="text-sm font-medium text-ink">{incident.alert}</div>
        {incident.symptoms.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-ink-2">
            {incident.symptoms.map((s) => <li key={s}>{s}</li>)}
          </ul>
        )}
        {Object.keys(incident.metrics).length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(incident.metrics).map(([k, v]) => (
              <span key={k} className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-ink-2">{k}=<span className="text-ink">{String(v)}</span></span>
            ))}
          </div>
        )}
      </Card>
    </Message>
  )
}

function AgentMessage({ incident, mode }: { incident: LiveIncident; mode: Mode }) {
  const { runs, recordStep } = useApp()
  const run = runs[runKey(incident.id, mode)]
  const tag = mode === 'on'
    ? <span className="rounded border border-memory/40 bg-memory/10 px-1.5 py-px text-[11px] text-memory">memory ON</span>
    : <span className="rounded border border-line bg-surface-3 px-1.5 py-px text-[11px] text-ink-2">memory OFF</span>
  return (
    <Message kind="agent" name="Déjà Vu" meta={tag}>
      <Card className="px-4 py-3">
        {!run ? <div className="flex items-center gap-2 text-xs text-ink-3"><Spinner /> starting…</div> : (
          <>
            <RunTimeline run={run} />
            {run.result && (
              <div className="mt-4 border-t border-line pt-4">
                <AnalysisCard result={run.result}
                  actions={{ incident, onMark: (step, outcome) => recordStep(incident.id, step, outcome, true) }} />
              </div>
            )}
          </>
        )}
      </Card>
    </Message>
  )
}

function Feed({ incident }: { incident: LiveIncident }) {
  const { feeds } = useApp()
  return <>{(feeds[incident.id] ?? []).map((item, i) => <FeedEntry key={i} item={item} incidentId={incident.id} />)}</>
}

function FeedEntry({ item, incidentId }: { item: FeedItem; incidentId: string }) {
  const human = item.kind === 'step'
    ? <>Tried <span className="text-ink">“{item.step}”</span> — <span className={item.outcome === 'WORKED' ? 'text-good' : 'text-bad'}>{item.outcome}</span></>
    : <>Resolved the incident{item.ttr !== null && <> in <span className="text-good">{item.ttr} min</span> (demo clock)</>}.</>
  return (
    <>
      <Message kind="human" name="On-call engineer"><div className="text-sm text-ink-2">{human}</div></Message>
      <Message kind="agent" name="Déjà Vu" meta={<span className="text-xs text-memory">memory write</span>}>
        {item.retained ? (
          <div className="rounded-lg border border-memory/30 bg-memory/5 px-3 py-2">
            <div className="mb-1 flex items-center gap-1.5 text-xs text-memory">{Icon.save('h-3.5 w-3.5')} Retained to Hindsight under document {incidentId} — next time, I'll remember this.</div>
            <ul className="space-y-1">
              {item.texts.map((t, i) => <li key={i} className="font-mono text-[11px] leading-relaxed text-ink-2">{t}</li>)}
            </ul>
          </div>
        ) : (
          <div className="text-xs text-bad">Could not retain to memory: {item.error}</div>
        )}
      </Message>
    </>
  )
}

function ResolveBar({ incident, mode }: { incident: LiveIncident; mode: Mode }) {
  const { runs, resolve } = useApp()
  const suggested = runs[runKey(incident.id, mode)]?.result?.analysis.likely_root_cause ?? ''
  const [rootCause, setRootCause] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => setRootCause(''), [incident.id])
  if (incident.status === 'resolved') {
    return <div className="border-t border-line px-5 py-3 text-xs text-ink-3">Resolved · root cause: <span className="text-ink-2">{incident.root_cause}</span></div>
  }
  const submit = async () => {
    setBusy(true)
    try { await resolve(incident.id, rootCause || suggested, mode) } finally { setBusy(false) }
  }
  return (
    <div className="flex items-center gap-2 border-t border-line px-5 py-3">
      <input value={rootCause} onChange={(e) => setRootCause(e.target.value)} placeholder={suggested || 'Root cause…'}
        className="min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-memory/60 focus:outline-none" />
      <Button variant="primary" disabled={busy || !(rootCause || suggested)} onClick={submit}>
        {busy ? <Spinner /> : Icon.check('h-4 w-4')} Resolve &amp; retain postmortem
      </Button>
    </div>
  )
}

const SERVICES = ['checkout-api', 'payment-service', 'inventory-db', 'auth-service', 'notification-worker', 'redis-cache', 'api-gateway']

function EmptyChannel() {
  const { openCustom } = useApp()
  const [service, setService] = useState('auth-service')
  const [alert, setAlert] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-lg text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-memory/15 text-memory">{Icon.brain('h-6 w-6')}</div>
        <h2 className="text-lg font-semibold text-ink">No active incident</h2>
        <p className="mt-1 text-sm text-ink-2">Play a demo scenario from the bar above — or raise your own alert and see what Déjà Vu remembers.</p>
        <div className="mt-5 space-y-2 text-left">
          <div className="flex gap-2">
            <select value={service} onChange={(e) => setService(e.target.value)} className="rounded-lg border border-line bg-surface-2 px-2 text-sm text-ink">
              {SERVICES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <input value={alert} onChange={(e) => setAlert(e.target.value)} placeholder="e.g. Redis READONLY errors after failover"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-memory/60 focus:outline-none" />
          </div>
          <Button variant="primary" className="w-full justify-center" disabled={busy || alert.length < 5}
            onClick={async () => { setBusy(true); try { await openCustom({ service, severity: 'SEV2', alert, symptoms: [] }) } finally { setBusy(false) } }}>
            {busy ? <Spinner /> : Icon.alert('h-4 w-4')} Raise alert
          </Button>
        </div>
      </div>
    </div>
  )
}
