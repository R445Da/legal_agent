import { AnimatePresence, motion } from 'framer-motion'
import { Check, X } from 'lucide-react'
import type { OrbState } from '@/assistant/types'
import { cn } from '@/lib/utils'

/**
 * The agent's visible body. It communicates *state*, never reasoning:
 * idle breathes, listening follows the microphone level, processing sweeps,
 * working orbits, responding ripples, awaiting holds an amber halo,
 * completed flashes a check, error flashes rose.
 */

const SIZES = { xs: 28, sm: 40, md: 64, lg: 120, xl: 150 } as const

const PALETTE: Record<OrbState, { a: string; b: string; glow: string; ring: string }> = {
  idle: { a: '#6b6cff', b: '#17d7c6', glow: 'rgba(103,101,255,.30)', ring: 'rgba(129,140,248,.25)' },
  listening: { a: '#22d3ee', b: '#6b6cff', glow: 'rgba(34,211,238,.38)', ring: 'rgba(103,232,249,.45)' },
  processing: { a: '#7f67ff', b: '#c084fc', glow: 'rgba(127,103,255,.40)', ring: 'rgba(167,139,250,.35)' },
  working: { a: '#6b6cff', b: '#22d3ee', glow: 'rgba(99,102,241,.38)', ring: 'rgba(129,140,248,.35)' },
  responding: { a: '#17d7c6', b: '#6b6cff', glow: 'rgba(23,215,198,.34)', ring: 'rgba(94,234,212,.35)' },
  awaiting: { a: '#fbbf24', b: '#f97316', glow: 'rgba(251,191,36,.28)', ring: 'rgba(252,211,77,.45)' },
  completed: { a: '#34d399', b: '#17d7c6', glow: 'rgba(52,211,153,.34)', ring: 'rgba(110,231,183,.45)' },
  error: { a: '#fb7185', b: '#f97316', glow: 'rgba(251,113,133,.32)', ring: 'rgba(253,164,175,.45)' },
}

export const ORB_LABEL: Record<OrbState, string> = {
  idle: 'آماده', listening: 'در حال شنیدن', processing: 'در حال فهم پیام', working: 'در حال کار',
  responding: 'در حال پاسخ', awaiting: 'در انتظار تأیید شما', completed: 'انجام شد', error: 'نیاز به توجه',
}

export function AIOrb({ state = 'idle', size = 'md', level = 0, className }: { state?: OrbState; size?: keyof typeof SIZES; level?: number; className?: string }) {
  const px = SIZES[size]
  const c = PALETTE[state]
  const spin = state === 'processing' ? 2.2 : state === 'working' ? 3.6 : state === 'listening' ? 6 : 12
  const big = px >= 100

  return (
    <div className={cn('relative shrink-0', className)} style={{ width: px, height: px }} role="img" aria-label={`دستیار — ${ORB_LABEL[state]}`}>
      {/* glow */}
      <motion.div
        className="absolute rounded-full blur-2xl"
        style={{ inset: -px * 0.28, background: `radial-gradient(circle, ${c.glow}, transparent 65%)` }}
        animate={{ opacity: state === 'idle' ? [0.55, 0.85, 0.55] : 1, scale: state === 'listening' ? 1 + level * 0.35 : 1 }}
        transition={{ duration: state === 'idle' ? 5 : 0.25, repeat: state === 'idle' ? Infinity : 0 }}
      />

      {/* listening — rings follow the microphone level */}
      {state === 'listening' && [0, 1, 2].map((i) => (
        <motion.div key={i} className="absolute rounded-full border"
          style={{ inset: -4 - i * (px * 0.09), borderColor: c.ring }}
          animate={{ scale: 1 + level * (0.18 + i * 0.1), opacity: 0.65 - i * 0.18 }}
          transition={{ type: 'spring', stiffness: 260, damping: 18 }} />
      ))}

      {/* responding — outward ripples */}
      {state === 'responding' && [0, 1].map((i) => (
        <motion.div key={i} className="absolute inset-0 rounded-full border" style={{ borderColor: c.ring }}
          initial={{ scale: 1, opacity: 0.6 }} animate={{ scale: 1.55, opacity: 0 }}
          transition={{ duration: 1.8, repeat: Infinity, delay: i * 0.9, ease: 'easeOut' }} />
      ))}

      {/* awaiting — a steady halo that asks for a decision */}
      {state === 'awaiting' && (
        <motion.div className="absolute rounded-full border-2" style={{ inset: -6, borderColor: c.ring }}
          animate={{ opacity: [0.35, 0.9, 0.35] }} transition={{ duration: 2.4, repeat: Infinity }} />
      )}

      {/* conic body */}
      <motion.div
        className="absolute inset-0 rounded-full"
        style={{ background: `conic-gradient(from 210deg, ${c.a}, ${c.b}, ${c.a}cc, ${c.b}, ${c.a})` }}
        animate={{ rotate: 360, scale: state === 'listening' ? 1 + level * 0.06 : state === 'idle' ? [1, 1.03, 1] : 1, x: state === 'error' ? [0, -3, 3, -2, 2, 0] : 0 }}
        transition={{ rotate: { duration: spin, repeat: Infinity, ease: 'linear' }, scale: { duration: state === 'idle' ? 5.5 : 0.2, repeat: state === 'idle' ? Infinity : 0 }, x: { duration: 0.45 } }}
      />

      {/* core */}
      <div className="absolute rounded-full bg-ink-850" style={{ inset: Math.max(2, px * 0.035) }}>
        <div className="absolute inset-0 overflow-hidden rounded-full">
          <motion.div className="absolute rounded-full bg-gradient-to-br from-white/80 to-indigo-300/10 blur-[1px]"
            style={{ inset: '25%' }}
            animate={{ opacity: state === 'processing' ? [0.5, 0.95, 0.5] : 0.85, scale: state === 'responding' ? [1, 1.08, 1] : 1 }}
            transition={{ duration: state === 'processing' ? 1.1 : 1.6, repeat: ['processing', 'responding'].includes(state) ? Infinity : 0 }} />
          <div className="absolute rounded-full blur-lg" style={{ inset: '33%', background: c.glow }} />
          {state === 'processing' && (
            <motion.div className="absolute inset-0" style={{ background: `conic-gradient(from 0deg, transparent 0 70%, ${c.ring} 85%, transparent)` }}
              animate={{ rotate: 360 }} transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }} />
          )}
        </div>
        <AnimatePresence>
          {(state === 'completed' || state === 'error') && big && (
            <motion.div key={state} className="absolute inset-0 flex items-center justify-center"
              initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }}>
              {state === 'completed' ? <Check className="h-8 w-8 text-emerald-200" strokeWidth={2.2} /> : <X className="h-8 w-8 text-rose-200" strokeWidth={2.2} />}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* working — orbiting satellites */}
      {state === 'working' && (
        <motion.div className="absolute inset-0" animate={{ rotate: 360 }} transition={{ duration: 1.8, repeat: Infinity, ease: 'linear' }}>
          {[0, 120, 240].map((deg) => (
            <span key={deg} className="absolute left-1/2 top-1/2 rounded-full bg-white/80"
              style={{ width: Math.max(3, px * 0.05), height: Math.max(3, px * 0.05), transform: `rotate(${deg}deg) translateY(-${px * 0.62}px)`, boxShadow: `0 0 8px ${c.glow}` }} />
          ))}
        </motion.div>
      )}
    </div>
  )
}

/** A small status line that pairs with the orb. */
export function AgentStatus({ state, className }: { state: OrbState; className?: string }) {
  const tone = state === 'error' ? 'text-rose-200/80 border-rose-300/15 bg-rose-300/5'
    : state === 'awaiting' ? 'text-amber-200/85 border-amber-300/15 bg-amber-300/5'
    : state === 'idle' || state === 'completed' ? 'text-emerald-200/80 border-emerald-300/10 bg-emerald-300/5'
    : 'text-cyan-100/85 border-cyan-300/15 bg-cyan-300/5'
  const dot = state === 'error' ? 'bg-rose-300' : state === 'awaiting' ? 'bg-amber-300' : state === 'idle' || state === 'completed' ? 'bg-emerald-300' : 'bg-cyan-300'
  return (
    <span className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs', tone, className)}>
      <span className="relative flex h-1.5 w-1.5">
        {state !== 'idle' && state !== 'completed' && <span className={cn('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60', dot)} />}
        <span className={cn('relative inline-flex h-1.5 w-1.5 rounded-full', dot)} />
      </span>
      {state === 'idle' ? 'دستیار آماده' : ORB_LABEL[state]}
    </span>
  )
}
