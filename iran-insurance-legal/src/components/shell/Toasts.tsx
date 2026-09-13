import { AnimatePresence, motion } from 'framer-motion'
import { CircleCheck, Info, TriangleAlert, Undo2, X } from 'lucide-react'
import { useEffect } from 'react'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import type { Toast } from '@/assistant/types'

export function Toasts() {
  const toasts = useAssistant((s) => s.toasts)
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-24 z-[70] flex flex-col items-center gap-2 px-3 sm:bottom-6 sm:end-auto sm:start-6 sm:w-[420px] sm:items-start sm:px-0">
      <AnimatePresence>{toasts.map((t) => <ToastView key={t.id} t={t} />)}</AnimatePresence>
    </div>
  )
}

function ToastView({ t }: { t: Toast }) {
  const dismiss = useAssistant((s) => s.dismiss)
  useEffect(() => { const h = setTimeout(() => dismiss(t.id), t.undo ? 10_000 : 5000); return () => clearTimeout(h) }, [t, dismiss])
  const Icon = t.tone === 'success' ? CircleCheck : t.tone === 'error' ? TriangleAlert : Info
  return (
    <motion.div layout initial={{ opacity: 0, y: 16, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8, scale: 0.96 }}
      className="glass pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-2xl px-4 py-3">
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', t.tone === 'success' ? 'text-emerald-300' : t.tone === 'error' ? 'text-rose-300' : 'text-cyan-300')} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium">{t.title}</div>
        {t.detail && <div className="mt-0.5 text-xs leading-5 text-white/50">{t.detail}</div>}
      </div>
      {t.undo && (
        <button onClick={() => { void t.undo!(); dismiss(t.id) }} className="flex shrink-0 items-center gap-1 rounded-xl border border-white/10 bg-white/[.05] px-2.5 py-1.5 text-xs text-white/80 hover:bg-white/10">
          <Undo2 className="h-3.5 w-3.5" /> برگرداندن
        </button>
      )}
      <button onClick={() => dismiss(t.id)} aria-label="بستن" className="shrink-0 text-white/30 hover:text-white"><X className="h-3.5 w-3.5" /></button>
    </motion.div>
  )
}
