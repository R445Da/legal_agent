import { motion } from 'framer-motion'
import { Check, Hand, X } from 'lucide-react'
import type { EntryRun } from '@/api/types'
import { fa, ms } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * The entry pipeline as user-facing operational progress:
 *   تشخیص نوع → استخراج ← مستندات ← خط زمان ← مشابه‌ها ← برچسب‌ها ← ثبت
 * Steps and their timings only — never the model's reasoning.
 */
export const PIPELINE = [
  { id: 'classify', label: 'تشخیص نوع' },
  { id: 'extract', label: 'استخراج ساختاریافته' },
  { id: 'references', label: 'مستندات قانونی' },
  { id: 'timeline', label: 'خط زمان' },
  { id: 'similar', label: 'پرونده‌های مشابه' },
  { id: 'labels', label: 'برچسب‌ها' },
  { id: 'commit', label: 'ثبت در آرشیو' },
]

export function RunStepper({ run, compact }: { run: EntryRun; compact?: boolean }) {
  const byId = Object.fromEntries(run.steps.map((s) => [s.step_id, s]))
  return (
    <ol className={cn('grid gap-1.5', compact ? 'grid-cols-4 sm:grid-cols-7' : 'grid-cols-4 sm:grid-cols-7')}>
      {PIPELINE.map((p) => {
        const step = byId[p.id]
        const status = step?.status ?? (run.status === 'committed' ? 'done' : 'pending')
        const awaiting = status === 'awaiting_input'
        return (
          <li key={p.id} title={step?.error ?? step?.detail ?? undefined}
            className={cn('min-w-0 rounded-xl border px-1.5 py-2',
              awaiting ? 'border-amber-300/25 bg-amber-300/[.06]' : status === 'running' ? 'border-indigo-300/25 bg-indigo-300/[.06]' : status === 'failed' ? 'border-rose-300/25 bg-rose-400/[.06]' : 'border-white/[.06] bg-white/[.02]')}>
            <Dot status={status} />
            <div className={cn('mt-1.5 text-[10.5px] leading-[1.3]', status === 'pending' || status === 'skipped' ? 'text-white/30' : 'text-white/80')}>{awaiting ? 'در انتظار تأیید' : p.label}</div>
            {step?.ms ? <div className="tnum mt-0.5 text-[9.5px] text-white/30">{ms(step.ms)}</div> : null}
          </li>
        )
      })}
    </ol>
  )
}

function Dot({ status }: { status: string }) {
  if (status === 'done' || status === 'skipped') return <span className={cn('flex h-4 w-4 items-center justify-center rounded-full', status === 'skipped' ? 'bg-white/20 text-ink-900' : 'bg-emerald-300/90 text-emerald-950')}><Check className="h-2.5 w-2.5" strokeWidth={3} /></span>
  if (status === 'failed') return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-rose-300/90 text-rose-950"><X className="h-2.5 w-2.5" strokeWidth={3} /></span>
  if (status === 'awaiting_input') return <span className="flex h-4 w-4 items-center justify-center rounded-full bg-amber-300 text-amber-950"><Hand className="h-2.5 w-2.5" strokeWidth={2.5} /></span>
  if (status === 'running') return (
    <span className="relative flex h-4 w-4 items-center justify-center">
      <motion.span className="absolute inset-0 rounded-full bg-indigo-300/40" animate={{ scale: [1, 1.6, 1], opacity: [0.7, 0, 0.7] }} transition={{ duration: 1.6, repeat: Infinity }} />
      <span className="h-2.5 w-2.5 rounded-full bg-indigo-300" />
    </span>
  )
  return <span className="block h-4 w-4 rounded-full border border-white/15" />
}

export const stepCount = (run: EntryRun) => fa(run.steps.filter((s) => s.status === 'done').length)
