import { motion } from 'framer-motion'
import { ArrowUpLeft, CornerDownLeft, RotateCcw } from 'lucide-react'
import { ask } from '@/assistant/runtime'
import type { Message } from '@/assistant/types'
import type { Intent } from '@/api/types'
import { cn } from '@/lib/utils'
import { useShell } from '@/state/shell'
import { sectionById } from '@/sections/registry'
import { AnswerCard } from './AnswerCard'
import { EditGate } from './EditGate'
import { RunCard } from './RunCard'
import { WhyThis } from './WhyThis'

const QUICK: Record<Intent, string> = { query: 'پرسش از اسناد', law: 'پرسش از قوانین', cases: 'بایگانی پرونده‌ها', archive: 'ثبت مطلب', analytics: 'آمار', agent: 'پژوهش عاملی', chat: 'گفت‌وگو', unclear: '' }
const INTENT_TONE: Partial<Record<Intent, string>> = { query: 'text-sky-200 bg-sky-400/10', law: 'text-amber-200 bg-amber-400/10', cases: 'text-cyan-200 bg-cyan-400/10', archive: 'text-violet-200 bg-violet-400/10', analytics: 'text-emerald-200 bg-emerald-400/10', agent: 'text-rose-200 bg-rose-400/10', chat: 'text-white/60 bg-white/[.06]', unclear: 'text-amber-200 bg-amber-400/10' }

export function MessageView({ m, origin = 'assistant', compact }: { m: Message; origin?: 'home' | 'assistant'; compact?: boolean }) {
  const open = useShell((s) => s.open)

  if (m.role === 'user') {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col items-end gap-1">
        <div className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-es-md border border-white/[.08] bg-white/[.07] px-3.5 py-2 text-[13px] leading-6 text-white/90">{m.text}</div>
        {m.context?.section && (
          <div className="flex items-center gap-1 text-[10px] text-white/30">
            <CornerDownLeft className="h-3 w-3" /> در {sectionById(m.context.section).title}{m.context.entityLabel ? ` › ${m.context.entityLabel}` : m.context.entityId ? ` › ${m.context.entityId.slice(0, 12)}` : ''}
          </div>
        )}
      </motion.div>
    )
  }

  // An edit gate's outcome is shown inside the gate itself.
  if (m.editOf) return null

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-2.5">
      {m.intentLabel && <span className={cn('inline-block rounded-full px-2.5 py-0.5 text-[10.5px] font-medium', INTENT_TONE[m.intent ?? 'chat'])}>{m.intentLabel}</span>}
      {m.text && (
        <div className={cn('whitespace-pre-line text-[13.5px] leading-7 text-white/80', m.streaming && 'after:ms-0.5 after:inline-block after:h-3.5 after:w-1.5 after:animate-pulse after:rounded-sm after:bg-white/40 after:align-middle')}>{m.text}</div>
      )}
      {m.error && (
        <div className="space-y-2 rounded-2xl border border-rose-300/15 bg-rose-400/[.06] px-3 py-2.5 text-[12.5px] text-rose-100/90">
          <div>پاسخ ناموفق — {m.error}</div>
          {m.retry && <button onClick={() => void ask(m.retry!.text, origin, m.retry!.intent)} className="inline-flex items-center gap-1 rounded-lg border border-rose-200/20 px-2 py-1 text-[11.5px] hover:bg-rose-300/10"><RotateCcw className="h-3 w-3" /> تلاش دوباره</button>}
        </div>
      )}
      {m.runId && <RunCard runId={m.runId} compact={compact} />}
      {m.result?.pending_edit && !m.streaming && <EditGate m={m} />}
      {m.result && !m.streaming && <AnswerCard result={m.result} scope={m.scope} />}
      {!m.streaming && (m.route || m.clarify || (m.why && m.why.length > 0)) ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {m.route && origin === 'home' && (
            <button onClick={() => open(m.route!.section, { tab: m.route!.tab, record: m.route!.record, origin: 'intent' })} className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/[.04] px-3 py-1 text-[11px] text-white/70 hover:text-white">
              باز کردن {m.route.label} <ArrowUpLeft className="h-3 w-3" />
            </button>
          )}
          {m.clarify?.options.map((o) => (
            <button key={o} onClick={() => void ask(m.clarify!.original, origin, o)} className="rounded-full border border-indigo-300/15 bg-indigo-300/[.06] px-3 py-1 text-[11px] text-indigo-100/85 hover:text-white">{QUICK[o]}</button>
          ))}
          {m.why && m.why.length > 0 && <WhyThis signals={m.why} className="basis-full" />}
        </div>
      ) : null}
    </motion.div>
  )
}
