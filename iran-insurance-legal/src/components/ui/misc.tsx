import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn('inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-white/10 bg-white/[.05] px-1.5 font-sans text-[10px] text-white/50', className)}>{children}</kbd>
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('surface rounded-3xl', className)} {...props} />
}

export function CardHeader({ title, subtitle, right, className }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start justify-between gap-4 px-5 pt-4 pb-3', className)}>
      <div className="min-w-0">
        <div className="text-sm font-medium text-white/90">{title}</div>
        {subtitle && <div className="mt-0.5 text-xs text-white/35">{subtitle}</div>}
      </div>
      {right}
    </div>
  )
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('text-[12px] font-medium text-white/35', className)}>{children}</div>
}

type PillTone = 'neutral' | 'good' | 'warn' | 'bad' | 'info' | 'suggest'
const PILL: Record<PillTone, string> = {
  neutral: 'bg-white/[.05] text-white/60 border-white/[.06]',
  good: 'bg-emerald-400/10 text-emerald-200 border-emerald-300/15',
  warn: 'bg-amber-400/10 text-amber-200 border-amber-300/15',
  bad: 'bg-rose-400/10 text-rose-200 border-rose-300/15',
  info: 'bg-cyan-400/10 text-cyan-200 border-cyan-300/15',
  suggest: 'bg-violet-400/10 text-violet-200 border-dashed border-violet-300/35',
}

export function Pill({ tone = 'neutral', children, className, dot }: { tone?: PillTone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-medium', PILL[tone], className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />}
      {children}
    </span>
  )
}

export function Stat({ label, value, hint, tone, className }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'good' | 'bad' | 'neutral'; className?: string }) {
  return (
    <div className={cn('surface rounded-3xl p-4', className)}>
      <div className="text-xs text-white/40">{label}</div>
      <div className={cn('tnum mt-2 text-xl font-semibold tracking-tight', tone === 'bad' && 'text-rose-100', tone === 'good' && 'text-emerald-100')}>{value}</div>
      {hint && <div className="mt-1 text-[11px] text-white/35">{hint}</div>}
    </div>
  )
}

export function Empty({ icon, title, detail, action }: { icon?: ReactNode; title: string; detail?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon && <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-white/50">{icon}</div>}
      <div className="text-sm font-medium text-white/80">{title}</div>
      {detail && <div className="mt-1 max-w-sm text-xs text-white/40">{detail}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Meter({ value, max, tone = 'indigo', className }: { value: number; max: number; tone?: 'indigo' | 'amber' | 'rose' | 'emerald'; className?: string }) {
  const w = Math.max(2, Math.min(100, (value / Math.max(max, 1)) * 100))
  const color = { indigo: 'bg-indigo-300/80', amber: 'bg-amber-300/80', rose: 'bg-rose-300/80', emerald: 'bg-emerald-300/80' }[tone]
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-white/[.06]', className)}>
      <div className={cn('h-full rounded-full transition-[width] duration-500', color)} style={{ width: `${w}%` }} />
    </div>
  )
}
