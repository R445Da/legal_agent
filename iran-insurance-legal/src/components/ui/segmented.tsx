import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

/** Sub-navigation inside a workspace. Minimal, scrollable, with a sliding indicator. */
export function Segmented<T extends string>({ items, value, onChange, layoutId, className, counts }: {
  items: { id: T; label: string }[]
  value: T
  onChange: (id: T) => void
  layoutId: string
  className?: string
  counts?: Partial<Record<T, number>>
}) {
  return (
    <div className={cn('scrollbar-none flex max-w-full items-center gap-1 overflow-x-auto rounded-2xl border border-white/[.07] bg-white/[.025] p-1', className)} role="tablist">
      {items.map((it) => {
        const active = it.id === value
        return (
          <button key={it.id} role="tab" aria-selected={active} onClick={() => onChange(it.id)}
            className={cn('relative flex h-8 shrink-0 items-center gap-1.5 rounded-xl px-3 text-xs transition-colors', active ? 'text-white' : 'text-white/45 hover:text-white/80')}>
            {active && <motion.span layoutId={layoutId} className="absolute inset-0 rounded-xl border border-white/10 bg-white/[.08]" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
            <span className="relative">{it.label}</span>
            {counts?.[it.id] ? <span className="tnum relative rounded-full bg-white/10 px-1.5 text-[10px] text-white/70">{counts[it.id]}</span> : null}
          </button>
        )
      })}
    </div>
  )
}
