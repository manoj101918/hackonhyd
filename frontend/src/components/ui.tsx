import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('rounded-xl border border-line bg-surface', className)}>{children}</div>
}

export function Button({ variant = 'default', className, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default' | 'primary' | 'good' | 'bad' | 'ghost' }) {
  const styles = {
    default: 'border-line bg-surface-2 hover:bg-surface-3 text-ink',
    primary: 'border-memory/60 bg-memory/15 hover:bg-memory/25 text-ink',
    good: 'border-good/40 bg-good/10 hover:bg-good/20 text-good',
    bad: 'border-bad/40 bg-bad/10 hover:bg-bad/20 text-bad',
    ghost: 'border-transparent hover:bg-surface-2 text-ink-2',
  }[variant]
  return (
    <button
      {...props}
      className={cx('inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition',
        'disabled:cursor-not-allowed disabled:opacity-50', styles, className)}
    />
  )
}

const FACT_STYLE: Record<string, { label: string; cls: string; hint: string }> = {
  world: { label: 'world', cls: 'text-world border-world/40 bg-world/10', hint: 'What happened' },
  experience: { label: 'experience', cls: 'text-experience border-experience/40 bg-experience/10', hint: "Déjà Vu's own actions and their outcomes" },
  observation: { label: 'observation', cls: 'text-observation border-observation/40 bg-observation/10', hint: 'Pattern consolidated across incidents' },
}

export function FactBadge({ type }: { type: string | null }) {
  const s = FACT_STYLE[type ?? ''] ?? { label: type ?? 'memory', cls: 'text-ink-2 border-line', hint: '' }
  return (
    <span title={s.hint} className={cx('inline-flex items-center rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wide', s.cls)}>
      {s.label}
    </span>
  )
}

export function IncidentChip({ id, highlight }: { id: string; highlight?: boolean }) {
  return (
    <span className={cx('inline-flex shrink-0 items-center whitespace-nowrap rounded-md border px-1.5 py-px font-mono text-[11px]',
      highlight ? 'border-memory/60 bg-memory/20 text-ink' : 'border-memory/30 bg-memory-dim/60 text-memory')}>
      {id}
    </span>
  )
}

export function SevBadge({ sev }: { sev: string | null }) {
  if (!sev) return null
  const cls = sev === 'SEV1' ? 'bg-bad/15 text-bad border-bad/40' : sev === 'SEV2' ? 'bg-warn/15 text-warn border-warn/40' : 'bg-surface-3 text-ink-2 border-line'
  return <span className={cx('rounded border px-1.5 py-px font-mono text-[11px] font-medium', cls)}>{sev}</span>
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cx('inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent', className)} />
}

export function Dot({ ok }: { ok: boolean | null }) {
  return <span className={cx('inline-block h-2 w-2 rounded-full', ok === null ? 'bg-ink-3' : ok ? 'bg-good' : 'bg-bad')} />
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">{children}</h3>
      {right}
    </div>
  )
}

/** Tiny inline icons (stroke-based, inherit colour). */
export const Icon = {
  brain: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 4a3 3 0 0 0-3 3v.2A3 3 0 0 0 4 10a3 3 0 0 0 1 2.2A3 3 0 0 0 6 17a3 3 0 0 0 3 3V4z" />
      <path d="M15 4a3 3 0 0 1 3 3v.2A3 3 0 0 1 20 10a3 3 0 0 1-1 2.2A3 3 0 0 1 18 17a3 3 0 0 1-3 3V4z" />
    </svg>
  ),
  logs: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M4 6h16M4 12h10M4 18h13" /></svg>
  ),
  deploy: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12M7 8l5-5 5 5M5 21h14" /></svg>
  ),
  spark: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z" /></svg>
  ),
  alert: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17.5v.01" /></svg>
  ),
  check: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
  ),
  x: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
  ),
  save: (c = 'h-4 w-4') => (
    <svg className={c} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></svg>
  ),
  play: (c = 'h-3.5 w-3.5') => (
    <svg className={c} viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z" /></svg>
  ),
}

export const TOOL_META: Record<string, { label: string; memory: boolean; icon: (c?: string) => ReactNode }> = {
  recall_similar_incidents: { label: 'Recall memory', memory: true, icon: Icon.brain },
  reflect_root_cause: { label: 'Reflect over memory', memory: true, icon: Icon.spark },
  check_deploy_risk: { label: 'Deploy-risk check (memory)', memory: true, icon: Icon.spark },
  get_service_logs: { label: 'Read logs', memory: false, icon: Icon.logs },
  get_recent_deploys: { label: 'Recent deploys', memory: false, icon: Icon.deploy },
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return ''
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso)
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
