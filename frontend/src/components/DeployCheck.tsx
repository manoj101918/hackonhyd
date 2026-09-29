import { useEffect, useRef } from 'react'
import { useApp } from '../state'
import { Button, Card, cx, Icon, IncidentChip, Spinner } from './ui'

const SERVICES = ['payment-service', 'checkout-api', 'inventory-db', 'auth-service', 'notification-worker', 'redis-cache', 'api-gateway']

const RISK_STYLE = {
  high: { cls: 'border-bad/50 bg-bad/10 text-bad', label: 'HIGH RISK', icon: '▲' },
  medium: { cls: 'border-warn/50 bg-warn/10 text-warn', label: 'MEDIUM RISK', icon: '◆' },
  low: { cls: 'border-good/50 bg-good/10 text-good', label: 'LOW RISK', icon: '●' },
  unknown: { cls: 'border-line bg-surface-2 text-ink-2', label: 'UNKNOWN', icon: '?' },
}

/** "Has a change like this caused an outage before?" — asked before shipping, answered from memory. */
export function DeployCheck() {
  const { deploy, setDeploy, runDeployCheck, memoryOn, scenarios } = useApp()
  const preset = scenarios.find((s) => s.kind === 'deploy_check')
  const autoRan = useRef('')

  // Playing scenario 3 pre-fills the form; run it once automatically.
  useEffect(() => {
    if (deploy.status === 'idle' && deploy.change && preset && deploy.change === preset.planned_change && autoRan.current !== deploy.change) {
      autoRan.current = deploy.change
      runDeployCheck(deploy, memoryOn)
    }
  }, [deploy, preset, memoryOn, runDeployCheck])

  const r = deploy.result
  const style = RISK_STYLE[r?.risk.risk ?? 'unknown']
  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <h2 className="text-lg font-semibold text-ink">Deploy check</h2>
      <p className="mt-0.5 text-sm text-ink-2">Describe a planned change. Déjà Vu reflects over every past deploy and outage and tells you whether this has hurt you before.</p>

      <Card className="mt-4 space-y-3 p-4">
        <div className="flex gap-2">
          <select value={deploy.service} onChange={(e) => setDeploy({ ...deploy, service: e.target.value, status: 'idle', result: undefined })}
            className="rounded-lg border border-line bg-surface-2 px-2 text-sm text-ink">
            {SERVICES.map((s) => <option key={s}>{s}</option>)}
          </select>
          {preset && (
            <Button variant="ghost" className="!text-xs" onClick={() => setDeploy({ service: preset.service, change: preset.planned_change ?? '', status: 'idle' })}>
              Use scenario 3 example
            </Button>
          )}
        </div>
        <textarea value={deploy.change} rows={3} onChange={(e) => setDeploy({ ...deploy, change: e.target.value })}
          placeholder="e.g. payment-service config: lower the PayFlow HTTP client timeout from 8000ms to 2500ms…"
          className="w-full resize-none rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-memory/60 focus:outline-none" />
        <div className="flex items-center gap-3">
          <Button variant="primary" disabled={deploy.status === 'running' || deploy.change.length < 10} onClick={() => runDeployCheck(deploy, memoryOn)}>
            {deploy.status === 'running' ? <Spinner /> : Icon.spark('h-4 w-4')} Check risk
          </Button>
          <span className="text-xs text-ink-3">
            {memoryOn ? 'Memory ON — Hindsight reflect over incidents + deploys' : 'Memory OFF — generic judgement only'}
          </span>
        </div>
      </Card>

      {deploy.status === 'running' && (
        <div className="mt-4 flex items-center gap-2 text-sm text-ink-2"><Spinner className="text-memory" /> Reflecting over past deploys and the outages that followed…</div>
      )}
      {deploy.status === 'error' && <div className="mt-4 text-sm text-bad">{deploy.error}</div>}

      {r && deploy.status === 'done' && (
        <Card className="slide-in mt-4 p-5">
          <div className="flex items-start gap-4">
            <div className={cx('shrink-0 rounded-lg border px-3 py-2 text-center font-mono', style.cls)}>
              <div className="text-xl leading-none">{style.icon}</div>
              <div className="mt-1 text-[11px] font-semibold tracking-wider">{style.label}</div>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm leading-relaxed text-ink">{r.risk.verdict}</p>
              {r.risk.evidence_incident_ids.length > 0 ? (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
                  evidence {r.risk.evidence_incident_ids.map((id) => <IncidentChip key={id} id={id} />)}
                </div>
              ) : (
                <div className="mt-2 text-xs text-ink-3">{r.memory_mode === 'off' ? 'No evidence — memory is off.' : 'No matching past incidents.'}</div>
              )}
            </div>
          </div>
          <div className="mt-5 grid gap-5 md:grid-cols-2">
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Why</div>
              <ul className="space-y-1.5">{r.risk.reasons.map((x, i) => <li key={i} className="text-sm text-ink-2">• {x}</li>)}</ul>
            </div>
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Before you ship</div>
              <ul className="space-y-1.5">{r.risk.recommendations.map((x, i) => <li key={i} className="text-sm text-ink-2">→ {x}</li>)}</ul>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
