import { motion } from 'framer-motion'
import { ArrowUpLeft } from 'lucide-react'
import type { ArchiveState } from '@/api/types'
import { cn } from '@/lib/utils'
import { TONES, type SectionDef } from '@/sections/registry'

/** An app tile. Its layoutId is shared with the workspace it expands into. */
export function AppCard({ s, state, onOpen, index, open }: { s: SectionDef; state?: ArchiveState; onOpen: () => void; index: number; open?: boolean }) {
  const t = TONES[s.tone]
  const metric = state && s.metric ? s.metric(state) : null
  return (
    <motion.button
      layoutId={`section-${s.id}`}
      onClick={onOpen}
      initial={{ opacity: 0, y: 14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: 0.025 * index, type: 'spring', stiffness: 320, damping: 30 }}
      whileHover={{ y: -4 }}
      whileTap={{ scale: 0.97 }}
      style={{ borderRadius: 26 }}
      className={cn('group relative flex min-h-[172px] flex-col overflow-hidden border bg-gradient-to-br p-5 text-start transition-colors hover:bg-white/[.04]', t.card)}
    >
      <span className="pointer-events-none absolute -end-10 -top-10 h-32 w-32 rounded-full opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100" style={{ background: t.glow }} />
      <div className="flex items-start justify-between">
        <span className={cn('flex h-12 w-12 items-center justify-center rounded-2xl border bg-black/20 shadow-[inset_0_1px_0_rgba(255,255,255,.06)]', t.icon)}>
          <s.icon className="h-5 w-5" strokeWidth={1.8} />
        </span>
        <span className="flex items-center gap-1.5 text-[10px] text-white/35">
          {open && <span className="rounded-full border border-white/10 px-1.5 py-0.5 text-white/50">باز</span>}
          <span className="tnum">{s.num}</span>
          <ArrowUpLeft className="h-3.5 w-3.5 transition group-hover:text-white" />
        </span>
      </div>
      <div className="mt-auto pt-5">
        <div className="text-[15px] font-semibold">{s.title}</div>
        <div className="mt-1 text-xs leading-5 text-white/40">{s.description}</div>
        {metric && (
          <div className="mt-3 flex items-center gap-2 text-[11px] text-white/60">
            <span className={cn('h-1.5 w-1.5 rounded-full', metric.attention ? t.dot : 'bg-white/25')} />
            {metric.label}
          </div>
        )}
      </div>
    </motion.button>
  )
}
