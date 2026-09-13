import { AnimatePresence, motion } from 'framer-motion'
import { Eraser, Minus } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { ask } from '@/assistant/runtime'
import { useIsMobile } from '@/hooks/useMedia'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { useCurrentContext } from '@/state/context'
import { useShell } from '@/state/shell'
import { blendOrb, useVoiceSignal } from '@/state/voice'
import { sectionById } from '@/sections/registry'
import { AIComposer } from './AIComposer'
import { AIOrb, ORB_LABEL } from './AIOrb'
import { MessageControls } from './MessageControls'
import { MessageView } from './Thread'

const SUGGESTIONS: Partial<Record<string, string[]>> = {
  cases: ['کارشناس در این پرونده چه نظری داد؟', 'پرونده‌های مشابه این پرونده چطور تمام شده‌اند؟', 'مهلت‌های این پرونده چیست؟'],
  laws: ['ماده ۳۰ قانون بیمه دربارهٔ جانشینی بیمه‌گر چه می‌گوید؟', 'مرور زمان دعاوی بیمه چقدر است؟'],
  analytics: ['چند پرونده شخص ثالث داریم؟', 'کدام وکلا بیشترین پرونده را دارند؟'],
  search: ['در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟'],
  ingest: ['پروندهٔ جدید'],
  default: ['پرونده‌های بازیافت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟', 'صف بازبینی را باز کن', 'چند پرونده شخص ثالث داریم؟'],
}

/** The floating, context-aware assistant inside every section. */
export function AssistantDrawer() {
  const open = useShell((s) => s.assistantOpen)
  const setOpen = useShell((s) => s.setAssistant)
  const ctx = useCurrentContext()
  const messages = useAssistant((s) => s.messages)
  const runs = useAssistant((s) => s.runs)
  const orb = useAssistant((s) => s.orb)
  const clear = useAssistant((s) => s.clear)
  const busy = useAssistant((s) => s.busy)
  const voice = useVoiceSignal()
  const mobile = useIsMobile()
  const waiting = useMemo(() => Object.values(runs).filter((r) => r.status === 'awaiting_input').length, [runs])
  const scroller = useRef<HTMLDivElement>(null)
  const state = blendOrb(orb, voice.phase)
  const last = messages.at(-1)

  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' }) }, [messages.length, last?.text, open])

  const chips = [
    ctx.section && { k: 'بخش', v: sectionById(ctx.section).title },
    ctx.entityId && { k: ctx.entityKind === 'case' ? 'پرونده' : ctx.entityKind === 'law' ? 'ماده' : ctx.entityKind === 'document' ? 'سند' : 'مورد', v: ctx.entityLabel ?? ctx.entityId.slice(0, 14) },
    ctx.view && { k: 'نما', v: ctx.view },
    !ctx.entityId && ctx.tabLabel && { k: 'نما', v: ctx.tabLabel },
    ...Object.entries(ctx.filters ?? {}).map(([k, v]) => ({ k, v })),
  ].filter(Boolean) as { k: string; v: string }[]
  const suggestions = SUGGESTIONS[ctx.entityKind === 'case' ? 'cases' : ctx.section ?? 'default'] ?? SUGGESTIONS.default!

  return (
    <>
      <AnimatePresence>
        {!open && (
          <motion.button key="fab" onClick={() => setOpen(true)} aria-label="باز کردن دستیار"
            initial={{ opacity: 0, scale: 0.8, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.8, y: 12 }}
            whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }}
            className="glass fixed bottom-5 end-5 z-40 flex items-center gap-3 rounded-full py-2 pe-4 ps-2 sm:bottom-6 sm:end-6">
            <AIOrb state={state} size="sm" level={voice.level} />
            <span className="text-start">
              <span className="block text-[13px] font-medium leading-5">دستیار حقوقی</span>
              <span className="block text-[10.5px] leading-4 text-white/40">{state === 'idle' ? 'دربارهٔ همین صفحه بپرسید' : ORB_LABEL[state]}</span>
            </span>
            {waiting > 0 && <span className="tnum absolute -end-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-300 px-1 text-[10px] font-semibold text-amber-950">{fa(waiting)}</span>}
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <>
            {mobile && <motion.div key="scrim" className="fixed inset-0 z-40 bg-black/40" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setOpen(false)} />}
            <motion.aside key="panel" role="dialog" aria-label="دستیار حقوقی"
              initial={mobile ? { y: '100%' } : { opacity: 0, scale: 0.94, y: 16 }}
              animate={mobile ? { y: 0 } : { opacity: 1, scale: 1, y: 0 }}
              exit={mobile ? { y: '100%' } : { opacity: 0, scale: 0.96, y: 12 }}
              transition={{ type: 'spring', stiffness: 380, damping: 34 }}
              drag={mobile ? 'y' : false} dragConstraints={{ top: 0, bottom: 0 }} dragElastic={{ top: 0, bottom: 0.5 }}
              onDragEnd={(_, info) => { if (info.offset.y > 120) setOpen(false) }}
              style={{ originX: 0, originY: 1 }}
              className={cn('glass fixed z-50 flex flex-col overflow-hidden',
                mobile ? 'inset-x-0 bottom-0 h-[86dvh] rounded-t-[28px]' : 'bottom-5 end-5 h-[min(760px,calc(100dvh-100px))] w-[min(480px,calc(100vw-40px))] rounded-[28px] sm:bottom-6 sm:end-6')}>
              {mobile && <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-white/15" />}
              <header className="flex items-center gap-3 px-4 pb-3 pt-4">
                <AIOrb state={state} size="sm" level={voice.level} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold">دستیار حقوقی</div>
                  <div className="text-[11px] text-white/40">{ORB_LABEL[state]} · آگاه از زمینهٔ صفحه</div>
                </div>
                <button onClick={clear} aria-label="گفتگوی جدید" title="گفتگوی جدید" className="flex h-8 w-8 items-center justify-center rounded-xl text-white/40 hover:bg-white/[.06] hover:text-white"><Eraser className="h-4 w-4" /></button>
                <button onClick={() => setOpen(false)} aria-label="کوچک کردن" className="flex h-8 w-8 items-center justify-center rounded-xl text-white/40 hover:bg-white/[.06] hover:text-white"><Minus className="h-4 w-4" /></button>
              </header>

              {chips.length > 0 && (
                <div className="scrollbar-none flex gap-1.5 overflow-x-auto border-y border-white/[.05] bg-white/[.015] px-4 py-2">
                  {chips.map((c) => (
                    <span key={c.k + c.v} className="shrink-0 rounded-full border border-white/[.07] bg-white/[.03] px-2.5 py-1 text-[10.5px]"><span className="text-white/35">{c.k}</span> <span className="text-white/75">{c.v}</span></span>
                  ))}
                </div>
              )}

              <div ref={scroller} className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
                {messages.length === 0 && (
                  <div className="rounded-2xl border border-white/[.06] bg-white/[.03] p-3.5 text-[13px] leading-7 text-white/65">
                    {ctx.entityKind === 'case'
                      ? <>پروندهٔ <b className="font-medium text-white">{ctx.entityLabel ?? ctx.entityId}</b> باز است. پرسش شما فقط از اسناد همین پرونده پاسخ داده می‌شود — لازم نیست زمینه را تکرار کنید.</>
                      : <>در <b className="font-medium text-white">{ctx.section ? sectionById(ctx.section).title : 'فضای کار'}</b> هستید. بپرسید، مطلب جدید ثبت کنید یا بخواهید بخشی باز شود.</>}
                  </div>
                )}
                {messages.slice(-40).map((m) => <MessageView key={m.id} m={m} compact />)}
              </div>

              <div className="space-y-2 border-t border-white/[.05] px-3 pb-3 pt-2.5">
                <div className="scrollbar-none flex gap-1.5 overflow-x-auto">
                  {suggestions.map((q) => <button key={q} disabled={busy} onClick={() => void ask(q, 'assistant')} className="shrink-0 rounded-full border border-white/[.07] bg-white/[.03] px-2.5 py-1 text-[11px] text-white/55 transition hover:text-white disabled:opacity-40">{q}</button>)}
                </div>
                <AIComposer origin="assistant" size="sm" placeholder={ctx.entityKind === 'case' ? 'از این پرونده بپرسید…' : 'بپرسید یا ثبت کنید…'} />
                <MessageControls compact className="justify-start" />
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  )
}
