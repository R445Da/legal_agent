import type { ReactNode } from 'react'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Label / value rows — the ledger `kv()` of the Streamlit theme. */
export function KV({ rows, className }: { rows: [string, ReactNode][]; className?: string }) {
  return (
    <dl className={cn('divide-y divide-white/[.05]', className)}>
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-baseline justify-between gap-4 py-2.5 text-[13px]">
          <dt className="shrink-0 text-white/40">{k}</dt>
          <dd className="min-w-0 text-end text-white/85">{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Chips({ items, tone = 'slate', onClick, className }: { items: string[]; tone?: 'slate' | 'teal' | 'amber' | 'violet'; onClick?: (s: string) => void; className?: string }) {
  if (!items.length) return <span className="text-xs text-white/30">—</span>
  const t = { slate: 'border-white/[.08] bg-white/[.04] text-white/70', teal: 'border-cyan-300/15 bg-cyan-300/[.07] text-cyan-100/90', amber: 'border-amber-300/15 bg-amber-300/[.06] text-amber-100/90', violet: 'border-violet-300/15 bg-violet-300/[.07] text-violet-100/90' }[tone]
  return (
    <div className={cn('flex flex-wrap gap-1.5', className)}>
      {items.map((i) => onClick
        ? <button key={i} onClick={() => onClick(i)} className={cn('rounded-full border px-2.5 py-0.5 text-[11.5px] transition hover:brightness-125', t)}>{i}</button>
        : <span key={i} className={cn('rounded-full border px-2.5 py-0.5 text-[11.5px]', t)}>{i}</span>)}
    </div>
  )
}

/** A case number stamp (mono, LTR-isolated). */
export function CaseNo({ value, className }: { value?: string | null; className?: string }) {
  return <span className={cn('ltr inline-block rounded-md border border-cyan-300/20 bg-cyan-300/[.07] px-1.5 font-mono text-[11px] text-cyan-100', className)}>{value ? fa(value) : '—'}</span>
}

export interface TimelineItem { date?: string | null; title: ReactNode; detail?: ReactNode; source?: string; tone?: 'manual' | 'default'; onClick?: () => void }

export function Timeline({ items }: { items: TimelineItem[] }) {
  if (!items.length) return <div className="py-6 text-center text-xs text-white/35">رویدادی ثبت نشده است.</div>
  return (
    <ol className="relative ms-2 space-y-4 border-s border-white/[.08] ps-5 pt-1">
      {items.map((e, i) => (
        <li key={i} className="relative">
          <span className={cn('absolute -start-[25px] top-2 h-2 w-2 rounded-full ring-4 ring-ink-900', e.tone === 'manual' ? 'bg-amber-300' : 'bg-cyan-300/80')} />
          <div className="tnum text-[11px] text-white/40">{fa(e.date ?? '—')}{e.source ? ` · ${e.source}` : ''}</div>
          {e.onClick ? <button onClick={e.onClick} className="text-start text-[13px] leading-6 text-white/85 hover:text-white">{e.title}</button> : <div className="text-[13px] leading-6 text-white/85">{e.title}</div>}
          {e.detail && <div className="text-[11.5px] leading-5 text-white/40">{e.detail}</div>}
        </li>
      ))}
    </ol>
  )
}

export function Bar({ value, max, tone = 'cyan' }: { value: number; max: number; tone?: 'cyan' | 'amber' | 'violet' | 'emerald' }) {
  const w = Math.max(2, Math.min(100, (value / Math.max(max, 1)) * 100))
  const c = { cyan: 'bg-cyan-300/70', amber: 'bg-amber-300/70', violet: 'bg-violet-300/70', emerald: 'bg-emerald-300/70' }[tone]
  return <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[.06]"><div className={cn('h-full rounded-full', c)} style={{ width: `${w}%` }} /></div>
}
