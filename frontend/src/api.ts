// Typed client for the Déjà Vu backend (see backend/dejavu/main.py).

export type FactType = 'world' | 'experience' | 'observation'
export type Outcome = 'WORKED' | 'FAILED' | 'PARTIAL'

export interface MemoryHit {
  id: string
  text: string
  type: FactType | string | null
  incident_ids: string[]
  date: string | null
  context: string | null
  score: number | null
  proof_count: number | null
  source: 'recall' | 'reflect' | 'list'
}

export interface MemoryStatus { available: boolean; bank_id: string; base_url: string; reason: string | null }
export interface Health { ok: boolean; memory: MemoryStatus; llm: { configured: boolean; models: string[] } }

export interface Scenario {
  id: string
  kind: 'incident' | 'deploy_check'
  title: string
  service: string
  severity: string | null
  alert?: string
  planned_change?: string
}

export interface StepRecord { step: string; outcome: Outcome; notes: string; at: string; sim_minute: number; from_agent: boolean; retained: boolean }

export interface LiveIncident {
  id: string
  scenario_id: string | null
  title: string
  service: string
  severity: string
  alert: string
  symptoms: string[]
  metrics: Record<string, string | number>
  started_at: string
  status: 'open' | 'resolved'
  steps: StepRecord[]
  resolved_at: string | null
  ttr_minutes: number | null
  root_cause: string | null
  memory_mode: 'on' | 'off' | null
}

export interface RecommendedStep { step: string; rationale: string; evidence_incident_ids: string[] }
export interface AvoidStep { step: string; reason: string; evidence_incident_ids: string[] }
export interface SimilarIncident { id: string; date: string | null; similarity_reason: string }

export interface IncidentAnalysis {
  summary: string
  likely_root_cause: string
  confidence: 'low' | 'medium' | 'high'
  recommended_steps: RecommendedStep[]
  avoid_steps: AvoidStep[]
  similar_incidents: SimilarIncident[]
}

export interface AnalysisMeta {
  memory_mode: 'on' | 'off'
  memory_available: boolean
  history_found: boolean
  model: string | null
  steps: number
  retries: number
  degraded: boolean
  degraded_reason: string | null
  elapsed_ms: number
  stripped_citations: string[]
}

export interface AnalysisResult { incident_id: string; analysis: IncidentAnalysis; memories: MemoryHit[]; meta: AnalysisMeta }

export type AgentEvent =
  | { type: 'status'; t_ms: number; message: string }
  | { type: 'tool_call'; t_ms: number; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; t_ms: number; id: string; name: string; summary: string; memories: MemoryHit[] }
  | { type: 'retry'; t_ms: number; model: string; retries: number }
  | { type: 'degraded'; t_ms: number; reason: string }
  | { type: 'memory_unavailable'; t_ms: number; reason: string | null }
  | { type: 'final'; t_ms: number; result: AnalysisResult }
  | { type: 'error'; t_ms?: number; message: string }

export interface DeployRisk {
  risk: 'low' | 'medium' | 'high' | 'unknown'
  verdict: string
  reasons: string[]
  evidence_incident_ids: string[]
  recommendations: string[]
}
export interface DeployCheckResponse { risk: DeployRisk; memories: MemoryHit[]; memory_mode: 'on' | 'off'; memory_available: boolean }

export interface StepOutcomeResponse { incident: LiveIncident; retained: boolean; retained_texts: string[]; error: string | null }

export interface CurvePoint {
  id: string; date: string; ttr_minutes: number; service: string; severity: string; title: string
  source: 'history' | 'live'; assisted: boolean
}

export interface LearnedGroup { title: string; observations: MemoryHit[] }
export interface Learned { available: boolean; reason?: string; groups: LearnedGroup[]; playbook: { name: string; content: string; updated_at: string | null } | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: () => request<Health>('/api/health'),
  scenarios: () => request<Scenario[]>('/api/scenarios'),
  incidents: () => request<LiveIncident[]>('/api/incidents'),
  startScenario: (id: string) => post<LiveIncident>(`/api/scenarios/${id}/start`),
  createIncident: (body: { service: string; severity: string; alert: string; symptoms: string[] }) =>
    post<LiveIncident>('/api/incidents', body),
  recordStep: (incidentId: string, body: { step: string; outcome: Outcome; notes?: string; from_agent: boolean }) =>
    post<StepOutcomeResponse>(`/api/incidents/${incidentId}/steps`, body),
  resolve: (incidentId: string, body: { root_cause: string; memory_mode: 'on' | 'off' }) =>
    post<StepOutcomeResponse>(`/api/incidents/${incidentId}/resolve`, body),
  deployCheck: (body: { service: string; change_description: string; memory: boolean }) =>
    post<DeployCheckResponse>('/api/deploy-check', body),
  learningCurve: () => request<CurvePoint[]>('/api/dashboard/learning-curve'),
  learned: () => request<Learned>('/api/memory/observations'),
  stats: () => request<{ available: boolean; counts: Partial<Record<FactType, number>> }>('/api/memory/stats'),
  search: (q: string) => request<{ available: boolean; memories: MemoryHit[] }>(`/api/memory/search?q=${encodeURIComponent(q)}`),
  resetDemo: () => post<{ ok: boolean }>('/api/demo/reset'),
}

/** POST + Server-Sent Events: streams the agent's progress, one event at a time. */
export async function streamAnalysis(
  incidentId: string,
  memory: boolean,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/incidents/${incidentId}/analyze?memory=${memory}`, { method: 'POST', signal })
  if (!res.ok || !res.body) throw new Error(`${res.status} ${await res.text()}`)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const data = block.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('')
      if (data) onEvent(JSON.parse(data) as AgentEvent)
    }
  }
}
