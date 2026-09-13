import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface MenuItem { label: string; icon?: ReactNode; hint?: string; onSelect: () => void; danger?: boolean }

export function Menu({ trigger, items, align = 'end', label }: { trigger: (open: boolean) => ReactNode; items: (MenuItem | 'sep')[]; align?: 'start' | 'end'; label: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])
  return (
    <div ref={ref} className="relative">
      <div onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} aria-label={label}>{trigger(open)}</div>
      <AnimatePresence>
        {open && (
          <motion.div role="menu" initial={{ opacity: 0, y: -4, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98 }} transition={{ duration: 0.14 }}
            className={cn('glass absolute top-full z-50 mt-2 min-w-56 rounded-2xl p-1.5', align === 'end' ? 'end-0' : 'start-0')}>
            {items.map((it, i) => it === 'sep' ? <div key={i} className="my-1 h-px bg-white/[.06]" /> : (
              <button key={it.label} role="menuitem" onClick={() => { setOpen(false); it.onSelect() }}
                className={cn('flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-start text-xs transition hover:bg-white/[.07]', it.danger ? 'text-rose-200/90' : 'text-white/75 hover:text-white')}>
                {it.icon && <span className="text-white/45">{it.icon}</span>}
                <span className="flex-1">{it.label}</span>
                {it.hint && <span className="text-[10px] text-white/30">{it.hint}</span>}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
