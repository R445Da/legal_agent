import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

/** Audio bars. Live when `bars` come from the microphone; a calm synthetic pulse otherwise. */
export function Waveform({ bars, active = true, className, color = 'bg-cyan-200/80' }: { bars?: number[]; active?: boolean; className?: string; color?: string }) {
  const n = bars?.length ?? 18
  return (
    <div className={cn('flex h-6 items-center gap-[3px]', className)} aria-hidden>
      {Array.from({ length: n }, (_, i) => {
        const v = bars ? bars[i] : 0
        return bars ? (
          <motion.span key={i} className={cn('w-[3px] rounded-full', color)} animate={{ height: `${Math.max(12, v * 100)}%`, opacity: 0.35 + v * 0.65 }} transition={{ duration: 0.08 }} />
        ) : (
          <motion.span key={i} className={cn('w-[3px] rounded-full', color)} style={{ height: '30%' }}
            animate={active ? { height: ['22%', `${40 + ((i * 37) % 55)}%`, '22%'] } : { height: '18%' }}
            transition={{ duration: 0.9 + (i % 5) * 0.12, repeat: Infinity, ease: 'easeInOut', delay: i * 0.04 }} />
        )
      })}
    </div>
  )
}
