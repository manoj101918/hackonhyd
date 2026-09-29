import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  api, streamAnalysis, type AgentEvent, type AnalysisResult, type DeployCheckResponse, type FactType, type Health,
  type LiveIncident, type Outcome, type Scenario,
} from './api'

export type Tab = 'channel' | 'compare' | 'deploy' | 'learning'
export type Mode = 'on' | 'off'

export interface Run {
  status: 'running' | 'done' | 'error'
  events: AgentEvent[]
  result?: AnalysisResult
  error?: string
}

/** Things that happened in an incident channel besides analyses: steps tried and memory writes. */
export type FeedItem =
  | { kind: 'step'; at: number; step: string; outcome: Outcome; retained: boolean; texts: string[]; error: string | null }
  | { kind: 'resolved'; at: number; ttr: number | null; retained: boolean; texts: string[]; error: string | null }

export interface DeployState {
  service: string
  change: string
  status: 'idle' | 'running' | 'done' | 'error'
  result?: DeployCheckResponse
  error?: string
}

export const DEMO_CLOCK_SPEED = 10 // must match backend world.DEMO_CLOCK_SPEED
export const runKey = (incidentId: string, mode: Mode) => `${incidentId}:${mode}`

function useAppState() {
  const [health, setHealth] = useState<Health | null>(null)
  const [counts, setCounts] = useState<Partial<Record<FactType, number>>>({})
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [memoryOn, setMemoryOn] = useState(true)
  const [tab, setTab] = useState<Tab>('channel')
  const [incidents, setIncidents] = useState<LiveIncident[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [runs, setRuns] = useState<Record<string, Run>>({})
  const [feeds, setFeeds] = useState<Record<string, FeedItem[]>>({})
  const [deploy, setDeploy] = useState<DeployState>({ service: 'payment-service', change: '', status: 'idle' })
  const [now, setNow] = useState(() => Date.now())
  const aborts = useRef<Record<string, AbortController>>({})

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health())
      const s = await api.stats()
      if (s.available) setCounts(s.counts)
    } catch {
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    refreshHealth()
    api.scenarios().then(setScenarios).catch(() => {})
    api.incidents().then((list) => {
      setIncidents(list)
      if (list[0]) setActiveId(list[0].id)
    }).catch(() => {})
    const t = setInterval(() => setNow(Date.now()), 1000)
    const h = setInterval(refreshHealth, 30000)
    return () => { clearInterval(t); clearInterval(h) }
  }, [refreshHealth])

  const upsertIncident = useCallback((inc: LiveIncident) => {
    setIncidents((list) => [inc, ...list.filter((i) => i.id !== inc.id)].sort((a, b) => b.started_at.localeCompare(a.started_at)))
  }, [])

  const analyze = useCallback(async (incidentId: string, mode: Mode) => {
    const key = runKey(incidentId, mode)
    aborts.current[key]?.abort()
    const ctrl = new AbortController()
    aborts.current[key] = ctrl
    setRuns((r) => ({ ...r, [key]: { status: 'running', events: [] } }))
    const push = (e: AgentEvent) => setRuns((r) => {
      const run = r[key] ?? { status: 'running', events: [] }
      const next: Run = { ...run, events: [...run.events, e] }
      if (e.type === 'final') { next.status = 'done'; next.result = e.result }
      if (e.type === 'error') { next.status = 'error'; next.error = e.message }
      return { ...r, [key]: next }
    })
    try {
      await streamAnalysis(incidentId, mode === 'on', push, ctrl.signal)
    } catch (err) {
      if (!ctrl.signal.aborted) push({ type: 'error', message: String(err) })
    }
  }, [])

  const playScenario = useCallback(async (scenario: Scenario) => {
    if (scenario.kind === 'deploy_check') {
      setTab('deploy')
      const next: DeployState = { service: scenario.service, change: scenario.planned_change ?? '', status: 'idle' }
      setDeploy(next)
      return next
    }
    const inc = await api.startScenario(scenario.id)
    upsertIncident(inc)
    setActiveId(inc.id)
    setTab((t) => (t === 'compare' ? 'compare' : 'channel'))
    return inc
  }, [upsertIncident])

  const openCustom = useCallback(async (body: { service: string; severity: string; alert: string; symptoms: string[] }) => {
    const inc = await api.createIncident(body)
    upsertIncident(inc)
    setActiveId(inc.id)
    return inc
  }, [upsertIncident])

  const addFeed = (incidentId: string, item: FeedItem) =>
    setFeeds((f) => ({ ...f, [incidentId]: [...(f[incidentId] ?? []), item] }))

  const recordStep = useCallback(async (incidentId: string, step: string, outcome: Outcome, fromAgent = true) => {
    const res = await api.recordStep(incidentId, { step, outcome, from_agent: fromAgent })
    upsertIncident(res.incident)
    addFeed(incidentId, { kind: 'step', at: Date.now(), step, outcome, retained: res.retained, texts: res.retained_texts, error: res.error })
    refreshHealth()
    return res
  }, [upsertIncident, refreshHealth])

  const resolve = useCallback(async (incidentId: string, rootCause: string, mode: Mode) => {
    const res = await api.resolve(incidentId, { root_cause: rootCause, memory_mode: mode })
    upsertIncident(res.incident)
    addFeed(incidentId, { kind: 'resolved', at: Date.now(), ttr: res.incident.ttr_minutes, retained: res.retained, texts: res.retained_texts, error: res.error })
    refreshHealth()
    return res
  }, [upsertIncident, refreshHealth])

  const runDeployCheck = useCallback(async (input: { service: string; change: string }, memory: boolean) => {
    setDeploy({ ...input, status: 'running' })
    try {
      const result = await api.deployCheck({ service: input.service, change_description: input.change, memory })
      setDeploy({ ...input, status: 'done', result })
    } catch (err) {
      setDeploy({ ...input, status: 'error', error: String(err) })
    }
  }, [])

  const resetDemo = useCallback(async () => {
    Object.values(aborts.current).forEach((c) => c.abort())
    await api.resetDemo()
    setIncidents([]); setActiveId(null); setRuns({}); setFeeds({})
    setDeploy({ service: 'payment-service', change: '', status: 'idle' })
  }, [])

  const active = incidents.find((i) => i.id === activeId) ?? null

  return {
    health, counts, scenarios, memoryOn, setMemoryOn, tab, setTab, incidents, active, activeId, setActiveId,
    runs, feeds, deploy, setDeploy, now, analyze, playScenario, openCustom, recordStep, resolve, runDeployCheck,
    resetDemo, refreshHealth,
  }
}

type AppState = ReturnType<typeof useAppState>
const Ctx = createContext<AppState | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={useAppState()}>{children}</Ctx.Provider>
}

export function useApp(): AppState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp outside AppProvider')
  return v
}

/** Simulated minutes since an incident started, on the demo clock. */
export function simMinutes(startedAt: string, now: number): number {
  return Math.max(0, ((now - Date.parse(startedAt)) / 1000) * DEMO_CLOCK_SPEED / 60)
}

export function fmtClock(minutes: number): string {
  const total = Math.floor(minutes * 60)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}
