import { AnimatePresence, motion } from 'framer-motion'
import { CircleHelp } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * «چرا این؟» — the signals and sources behind a suggestion or a route: which
 * words matched, which records, which rule. Never hidden model reasoning.
 */
export function WhyThis({ signals, className, label = 'چرا این؟' }: { signals: string[]; className?: string; label?: string }) {
  const [open, setOpen] = useState(false)
  const items = signals.filter(Boolean)
  if (!items.length) return null
  return (
    <div className={cn('relative', className)}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex items-center gap-1 text-[11px] text-white/40 transition hover:text-white/80">
        <CircleHelp className="h-3.5 w-3.5" /> {label}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
            <ul className="mt-2 space-y-1.5 rounded-2xl border border-white/[.06] bg-white/[.025] p-3">
              {items.map((s, i) => (
                <li key={i} className="flex gap-2 text-[11.5px] leading-6 text-white/60">
                  <span className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-indigo-300/70" />
                  <span>{s}</span>
                </li>
              ))}
              <li className="pt-1 text-[10px] text-white/25">نشانه‌ها و منابعی که به کار رفت — نه استدلال پنهان مدل.</li>
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
