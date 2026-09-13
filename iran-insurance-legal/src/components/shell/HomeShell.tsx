import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUpLeft, CalendarClock, ClipboardCheck, Eraser, FolderKanban, LayoutGrid } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/api/endpoints'
import { useArchive } from '@/api/queries'
import type { Intent } from '@/api/types'
import { ask } from '@/assistant/runtime'
import { compactRial, fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { useSettings } from '@/state/settings'
import { useShell } from '@/state/shell'
import { blendOrb, useVoiceSignal } from '@/state/voice'
import { TONES } from '@/sections/registry'
import { AIComposer } from '@/components/assistant/AIComposer'
import { AIOrb, AgentStatus } from '@/components/assistant/AIOrb'
import { ConversationsButton, FocusChip } from '@/components/assistant/Conversations'
import { MessageControls } from '@/components/assistant/MessageControls'
import { MessageView } from '@/components/assistant/Thread'
import { BrandMark, InboxButton, PaletteButton, PanelButton } from './TopActions'

const EXAMPLES: { text: string; intent?: Intent }[] = [
  { text: 'ماده ۳۰ قانون بیمه دربارهٔ جانشینی بیمه‌گر چه می‌گوید؟' },
  { text: 'پرونده‌های بازیافت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟' },
  { text: 'چند پرونده شخص ثالث داریم؟' },
  { text: 'صف بازبینی را باز کن' },
]

/**
 * ۰۱ دستیار پرونده — the AI home. "What do you want to accomplish?"
 * Empty: the orb, the question, the composer. Once you speak, it becomes the
 * conversation; navigation intents open the right section.
 */
export function HomeShell() {
  const messages = useAssistant((s) => s.messages)
  const orb = useAssistant((s) => s.orb)
  const clear = useAssistant((s) => s.clear)
  const voice = useVoiceSignal()
  const state = blendOrb(orb, voice.phase)
  const active = messages.length > 0

  return (
    <div className="mesh grid-bg relative flex min-h-full flex-col">
      <div className="pointer-events-none absolute -top-24 start-1/3 h-80 w-80 rounded-full bg-indigo-500/10 blur-3xl" />
      {/* Above the hero (also z-10, later in the DOM), so the «گفتگوها» list opens over it. */}
      <header className="relative z-20 flex items-center justify-between px-5 py-5 lg:px-10">
        <BrandMark />
        <div className="flex items-center gap-2">
          <ConversationsButton />
          {active && <button onClick={clear} className="flex h-10 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.04] px-3 text-xs text-white/60 hover:text-white"><Eraser className="h-3.5 w-3.5" /><span className="hidden sm:inline">گفتگوی جدید</span></button>}
          <AgentStatus state={state} className="hidden md:inline-flex" />
          <PaletteButton label="فرمان" />
          <InboxButton />
          <PanelButton />
        </div>
      </header>
      <AnimatePresence mode="wait" initial={false}>
        {active ? <Conversation key="conv" /> : <Hero key="hero" />}
      </AnimatePresence>
    </div>
  )
}

function Hero() {
  const orb = useAssistant((s) => s.orb)
  const voice = useVoiceSignal()
  const state = blendOrb(orb, voice.phase)
  const [seed, setSeed] = useState<{ text: string; n: number }>()
  const stages = useQuery({ queryKey: ['stages'], queryFn: api.demoStages, staleTime: Infinity })

  return (
    <motion.main initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -12 }} className="relative z-10 mx-auto w-full max-w-6xl flex-1 px-5 pb-16 pt-2 lg:px-10 lg:pt-6">
      <div className="flex flex-col items-center text-center">
        <motion.div layoutId="assistant-orb" transition={{ type: 'spring', stiffness: 200, damping: 26 }}>
          <AIOrb state={state} size="xl" level={voice.level} />
        </motion.div>
        <div className="mt-8 text-[12px] font-medium tracking-wide text-indigo-200/60">۰۱ · دستیار پرونده</div>
        <h1 className="mt-3 text-balance text-4xl font-extrabold leading-[1.25] tracking-tight sm:text-5xl lg:text-6xl">چه کاری می‌خواهید<br className="hidden sm:block" /> انجام دهید؟</h1>
        <p className="mt-4 max-w-2xl text-balance text-sm leading-7 text-white/45 sm:text-base">بپرسید، مطلب جدید ثبت کنید یا فقط بگویید — دستیار خودش تشخیص می‌دهد. هیچ چیزی بدون تأیید شما در آرشیو ثبت نمی‌شود.</p>

        <AIComposer origin="home" size="lg" autoFocus className="mt-8 max-w-3xl" seed={seed} />
        <MessageControls className="mt-3" />

        <div className="mt-5 flex max-w-3xl flex-wrap justify-center gap-2">
          {EXAMPLES.map((q) => (
            <button key={q.text} onClick={() => setSeed((s) => ({ text: q.text, n: (s?.n ?? 0) + 1 }))} className="rounded-full border border-white/10 bg-white/[.03] px-3 py-2 text-xs text-white/55 transition hover:bg-white/[.06] hover:text-white">{q.text}</button>
          ))}
        </div>
        {stages.data && stages.data.stages.length > 0 && (
          <div className="mt-3 flex max-w-4xl flex-wrap justify-center gap-2">
            <span className="self-center text-[11px] text-white/30">مراحل نمایش:</span>
            {stages.data.stages.map((st) => {
              const first = st.prompts[0]
              return (
                <button key={st.id} title={st.blurb} onClick={() => { if (first.mode) useSettings.getState().set({ runMode: first.mode }); void ask(first.text, 'home', first.intent ?? undefined) }}
                  className="rounded-full border border-indigo-300/15 bg-indigo-300/[.05] px-3 py-1.5 text-[11.5px] text-indigo-100/75 transition hover:text-white">{st.title}</button>
              )
            })}
          </div>
        )}
      </div>
      <HomeCards />
    </motion.main>
  )
}

function Conversation() {
  const messages = useAssistant((s) => s.messages)
  const bottom = useRef<HTMLDivElement>(null)
  const last = messages.at(-1)
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages.length, last?.text])
  return (
    <motion.main initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="relative z-10 mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 lg:px-0">
      <div className="flex-1 space-y-7 pb-8 pt-2">
        {messages.map((m) => <MessageView key={m.id} m={m} origin="home" />)}
        <div ref={bottom} />
      </div>
      <div className="sticky bottom-0 z-10 -mx-4 bg-gradient-to-t from-ink-900 via-ink-900/95 to-transparent px-4 pb-5 pt-6">
        <FocusChip className="mb-2" />
        <AIComposer origin="home" size="lg" autoFocus />
        <MessageControls className="mt-2.5" />
      </div>
    </motion.main>
  )
}

function HomeCards() {
  const { data } = useArchive()
  const { open, goPanel } = useShell()
  const upcoming = data?.events.slice(0, 1)[0]
  const cards = [
    { tone: 'cyan' as const, icon: <FolderKanban className="h-[18px] w-[18px]" />, badge: data ? `${fa(data.archive.cases)} پرونده` : '…', title: 'پرونده‌ها', detail: data ? `مجموع خواسته‌ها ${compactRial(data.archive.claim_total)} · ${fa(data.archive.citations)} استناد به ${fa(data.archive.laws)} ماده.` : 'در حال بارگذاری…', cta: 'باز کردن پرونده‌ها', onClick: () => open('cases', { origin: 'intent' }) },
    { tone: 'rose' as const, icon: <ClipboardCheck className="h-[18px] w-[18px]" />, badge: data ? (data.review_queue.length ? `${fa(data.review_queue.length)} در صف` : 'صف خالی') : '…', title: 'بازبینی انسانی', detail: data?.review_queue.length ? 'پرونده‌هایی که شماره یا طرفین آن‌ها استخراج نشد منتظر شما هستند.' : 'همهٔ پرونده‌ها کامل‌اند.', cta: 'صف بازبینی', onClick: () => open('review', { origin: 'intent' }) },
    { tone: 'sky' as const, icon: <CalendarClock className="h-[18px] w-[18px]" />, badge: data ? `${fa(data.events.length)} رویداد` : '…', title: 'آخرین رویداد', detail: upcoming ? `${fa(upcoming.date ?? '')} — ${fa(upcoming.description ?? upcoming.what ?? '')}`.slice(0, 110) : 'رویدادی ثبت نشده است.', cta: 'خط زمان', onClick: () => open('events', { origin: 'intent' }) },
    { tone: 'violet' as const, icon: <LayoutGrid className="h-[18px] w-[18px]" />, badge: '۱۹ بخش', title: 'پیشخوان بخش‌ها', detail: 'همهٔ بخش‌های آرشیو، ثبت، پژوهش و آزمایشگاه به‌صورت برنامه‌های مستقل.', cta: 'ورود به پیشخوان', onClick: goPanel },
  ]
  return (
    <div className="mt-14 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {cards.map((c) => {
        const t = TONES[c.tone]
        return (
          <motion.button key={c.title} onClick={c.onClick} whileHover={{ y: -3 }} whileTap={{ scale: 0.985 }} className="glass group rounded-3xl p-5 text-start transition-colors hover:bg-white/[.055]">
            <div className="flex items-start justify-between">
              <span className={cn('flex h-10 w-10 items-center justify-center rounded-2xl border', t.icon)}>{c.icon}</span>
              <span className={cn('text-[11px]', t.text)}>{c.badge}</span>
            </div>
            <div className="mt-8 text-lg font-semibold">{c.title}</div>
            <div className="mt-1 line-clamp-2 min-h-10 text-[13px] leading-6 text-white/45">{c.detail}</div>
            <div className="mt-5 flex items-center gap-1 text-xs text-white/55 transition group-hover:text-white">{c.cta} <ArrowUpLeft className="h-3.5 w-3.5" /></div>
          </motion.button>
        )
      })}
    </div>
  )
}
