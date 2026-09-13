import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, Copy, ExternalLink, FileText, House, Hand, MoreHorizontal, Plus, RefreshCw, Sparkles, X, Zap } from 'lucide-react'
import { useEffect } from 'react'
import { useRefreshArchive } from '@/api/queries'
import { ask } from '@/assistant/runtime'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { activeTab, isRunTab, serialize, useShell, type WorkspaceTab } from '@/state/shell'
import { sectionById, TONES } from '@/sections/registry'
import { SECTION_VIEWS } from '@/sections'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'
import { AIOrb } from '@/components/assistant/AIOrb'
import { WhyThis } from '@/components/assistant/WhyThis'
import { AssistantDrawer } from '@/components/assistant/AssistantDrawer'
import { Menu, type MenuItem } from '@/components/ui/menu'
import { Segmented } from '@/components/ui/segmented'
import { ContextBreadcrumb } from './ContextBreadcrumb'
import { InboxButton, PaletteButton } from './TopActions'

/**
 * A section workspace. Navigation shrinks to "→ بخش" at the start and
 * جستجو / کارها / بیشتر at the end; the rest of the screen belongs to the
 * section. Open sections are tabs; records and runs open as tabs inside them.
 */
export function WorkspaceShell() {
  const s = useShell()
  const ws = activeTab(s)
  if (!ws) return null
  const def = sectionById(ws.section)
  const View = SECTION_VIEWS[ws.section]
  const fromCard = s.origin === 'card'

  return (
    <motion.div
      layoutId={fromCard ? `section-${ws.section}` : undefined}
      style={{ borderRadius: 0 }}
      initial={fromCard ? false : { opacity: 0, scale: s.origin === 'intent' ? 0.97 : 1 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 32 }}
      className="absolute inset-0 overflow-hidden bg-ink-900"
    >
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: fromCard ? 0.16 : 0.04, duration: 0.3 }} className="flex h-full flex-col">
        <header className="z-20 border-b border-white/[.06] bg-ink-900/85 backdrop-blur-xl">
          <div className="flex items-center gap-2 px-3 py-3 sm:px-5 lg:px-8">
            <button onClick={s.goPanel} className="group flex min-w-0 items-center gap-2.5 rounded-2xl pe-2 text-start" aria-label="بازگشت به پیشخوان">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-white/70 transition group-hover:bg-white/[.08] group-hover:text-white"><ArrowRight className="h-[18px] w-[18px]" /></span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold">{def.title}</span>
                <span className="tnum block truncate text-[11px] text-white/30">{def.num} · {def.description}</span>
              </span>
            </button>
            <WorkspaceTabs />
            <MobileTabs />
            <div className="ms-auto flex items-center gap-2">
              <PaletteButton />
              <ActionsMenu ws={ws} />
              <InboxButton className="hidden sm:flex" />
              <MoreMenu ws={ws} />
            </div>
          </div>
          <div className="flex flex-col gap-2 px-3 pb-3 sm:px-5 lg:flex-row lg:items-center lg:px-8">
            <SectionAndInnerTabs ws={ws} />
            <div className="hidden min-w-0 lg:ms-auto lg:block"><ContextBreadcrumb /></div>
          </div>
        </header>

        <main className="relative flex-1 overflow-y-auto">
          <IntentBanner />
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={`${ws.section}:${ws.active ?? ws.tab}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2, ease: [0.2, 0.7, 0.2, 1] }}
              className="mx-auto max-w-7xl px-3 pb-32 pt-5 sm:px-5 lg:px-8">
              <ErrorBoundary resetKey={`${ws.section}:${ws.active ?? ws.tab}`}><View ws={ws} /></ErrorBoundary>
            </motion.div>
          </AnimatePresence>
        </main>
      </motion.div>
      <AssistantDrawer />
    </motion.div>
  )
}

function WorkspaceTabs() {
  const { tabs, active, open, close, goHome, goPanel } = useShell()
  return (
    <div className="scrollbar-none mx-2 hidden min-w-0 flex-1 items-center gap-1 overflow-x-auto md:flex" role="tablist" aria-label="بخش‌های باز">
      <button onClick={goHome} title="دستیار" aria-label="دستیار" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white/40 hover:bg-white/[.06] hover:text-white"><House className="h-4 w-4" /></button>
      {tabs.map((t) => {
        const d = sectionById(t.section)
        const isActive = t.section === active
        return (
          <div key={t.section} role="tab" aria-selected={isActive} className={cn('group relative flex h-8 shrink-0 items-center rounded-xl pe-1 ps-2.5 text-xs transition', isActive ? 'text-white' : 'text-white/45 hover:text-white/80')}>
            {isActive && <motion.span layoutId="ws-tab" className="absolute inset-0 rounded-xl border border-white/10 bg-white/[.07]" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
            <button onClick={() => open(t.section, { origin: 'tab' })} className="relative flex items-center gap-1.5">
              <d.icon className="h-3.5 w-3.5" style={{ color: isActive ? TONES[d.tone].hex : undefined }} />
              {d.title}
              {t.inner.length > 0 && <span className="tnum rounded-md bg-white/[.07] px-1 text-[10px] text-white/50">{fa(t.inner.length)}</span>}
            </button>
            <button onClick={() => close(t.section)} aria-label={`بستن ${d.title}`} className="relative ms-1 flex h-5 w-5 items-center justify-center rounded-md text-white/30 opacity-0 transition hover:bg-white/10 hover:text-white group-hover:opacity-100"><X className="h-3 w-3" /></button>
          </div>
        )
      })}
      <button onClick={goPanel} title="بخش دیگر" aria-label="باز کردن بخش دیگر" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-white/35 hover:bg-white/[.06] hover:text-white"><Plus className="h-4 w-4" /></button>
    </div>
  )
}

function MobileTabs() {
  const { tabs, active, open, goHome, goPanel } = useShell()
  return (
    <div className="md:hidden">
      <Menu label="بخش‌های باز" align="start" items={[
        { label: 'دستیار', icon: <House className="h-3.5 w-3.5" />, onSelect: goHome },
        ...tabs.map((t) => ({ label: sectionById(t.section).title, hint: t.section === active ? 'فعلی' : t.inner.length ? `${fa(t.inner.length)} باز` : undefined, onSelect: () => open(t.section, { origin: 'tab' }) })),
        'sep' as const,
        { label: 'باز کردن بخش دیگر', icon: <Plus className="h-3.5 w-3.5" />, onSelect: goPanel },
      ]} trigger={() => <button className="tnum flex h-8 min-w-8 items-center justify-center rounded-xl border border-white/10 bg-white/[.04] px-2 text-[11px] text-white/60">{fa(tabs.length)}</button>} />
    </div>
  )
}

function SectionAndInnerTabs({ ws }: { ws: WorkspaceTab }) {
  const { setTab, focusInner, closeInner } = useShell() // setTab also returns to the list view
  const def = sectionById(ws.section)
  return (
    <div className="scrollbar-none flex min-w-0 items-center gap-2 overflow-x-auto">
      {def.tabs.length > 1 || !ws.inner.length ? <Segmented layoutId={`seg-${ws.section}`} items={def.tabs} value={ws.active ? '' : ws.tab} onChange={setTab} /> : (
        <button onClick={() => focusInner(null)} className={cn('h-10 shrink-0 rounded-2xl border px-3 text-xs', ws.active ? 'border-white/[.06] text-white/50' : 'border-white/15 bg-white/[.08] text-white')}>{def.tabs[0].label}</button>
      )}
      {ws.inner.length > 0 && <span className="h-5 w-px shrink-0 bg-white/10" />}
      <AnimatePresence initial={false}>
        {ws.inner.map((i) => {
          const isActive = ws.active === i.id
          const run = isRunTab(i.id)
          return (
            <motion.div key={i.id} layout initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.9 }}
              className={cn('flex h-10 shrink-0 items-center gap-1 rounded-2xl border pe-1.5 ps-3 text-xs transition', isActive ? 'border-white/15 bg-white/[.08] text-white' : 'border-white/[.06] bg-white/[.02] text-white/50 hover:text-white/85')}>
              <button onClick={() => focusInner(i.id)} className="flex max-w-[180px] items-center gap-1.5">
                {run ? <Zap className="h-3.5 w-3.5 text-violet-300" /> : <FileText className="h-3.5 w-3.5 opacity-60" />}
                <span className="truncate font-medium">{i.label}</span>
              </button>
              <button onClick={() => closeInner(i.id)} aria-label={`بستن ${i.label}`} className="flex h-6 w-6 items-center justify-center rounded-lg text-white/35 hover:bg-white/10 hover:text-white"><X className="h-3 w-3" /></button>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

function IntentBanner() {
  const banner = useAssistant((s) => s.banner)
  const setBanner = useAssistant((s) => s.setBanner)
  const orb = useAssistant((s) => s.orb)
  const here = useShell((s) => serialize(s))
  const setAssistant = useShell((s) => s.setAssistant)
  useEffect(() => {
    if (!banner) return
    const t = setTimeout(() => setBanner(null), 12_000)
    return () => clearTimeout(t)
  }, [banner, setBanner])
  const show = banner && banner.view === here
  return (
    <AnimatePresence>
      {show && (
        <motion.div key={banner.id} initial={{ opacity: 0, y: -10, height: 0 }} animate={{ opacity: 1, y: 0, height: 'auto' }} exit={{ opacity: 0, y: -10, height: 0 }} className="overflow-hidden">
          <div className="mx-auto max-w-7xl px-3 pt-4 sm:px-5 lg:px-8">
            <div className="flex items-start gap-3 rounded-2xl border border-indigo-300/15 bg-gradient-to-l from-indigo-400/[.08] via-cyan-400/[.04] to-transparent px-4 py-3">
              <AIOrb state={orb === 'idle' ? 'completed' : orb} size="xs" className="mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-[11px] text-indigo-100/60"><Sparkles className="h-3 w-3" /> دستیار</div>
                <div className="mt-0.5 text-[13px] text-white/85">{banner.text}</div>
                <WhyThis signals={banner.why} className="mt-1" />
              </div>
              <button onClick={() => setAssistant(true)} className="hidden shrink-0 rounded-xl px-2.5 py-1.5 text-[11px] text-white/55 hover:bg-white/[.06] hover:text-white sm:block">ادامه با دستیار</button>
              <button onClick={() => setBanner(null)} aria-label="بستن" className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-white/35 hover:bg-white/[.06] hover:text-white"><X className="h-3.5 w-3.5" /></button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function ActionsMenu({ ws }: { ws: WorkspaceTab }) {
  const { setTab, open } = useShell()
  const refresh = useRefreshArchive()
  const items: Partial<Record<string, MenuItem[]>> = {
    cases: [{ label: 'پرونده‌های ناقص', onSelect: () => setTab('incomplete') }, { label: 'همگام‌سازی دوبارهٔ آرشیو', onSelect: () => open('settings', { tab: 'connection' }) }],
    ingest: [{ label: 'استخراج ساختاریافته', onSelect: () => setTab('structured') }, { label: 'بارگذاری فایل', onSelect: () => setTab('files') }, { label: 'اجراهای خط لوله', onSelect: () => setTab('runs') }],
    laws: [{ label: 'افزودن مادهٔ قانونی', onSelect: () => setTab('add') }],
    analytics: [{ label: 'پرسش زبانی از آمار', onSelect: () => setTab('ask') }],
    review: [{ label: 'پیشنهاد برنامهٔ کار', onSelect: () => void ask('صف بازبینی را خلاصه کن و بگو از کجا شروع کنم', 'assistant', 'chat') }],
    search: [{ label: 'آزمایشگاه بازیابی', onSelect: () => setTab('lab') }],
    webhooks: [{ label: 'تحویل‌ها', onSelect: () => setTab('deliveries') }, { label: 'CI', onSelect: () => setTab('ci') }],
  }
  const list: MenuItem[] = [
    ...(items[ws.section] ?? []),
    { label: 'ثبت مطلب جدید', icon: <Hand className="h-3.5 w-3.5" />, onSelect: () => open('ingest', { tab: 'structured' }) },
    { label: 'بازخوانی آرشیو', icon: <RefreshCw className="h-3.5 w-3.5" />, onSelect: () => void refresh() },
  ]
  return (
    <Menu label="کارها" items={list} trigger={(o) => (
      <button className={cn('flex h-10 items-center gap-1.5 rounded-2xl border px-3 text-xs transition', o ? 'border-white/20 bg-white/[.1] text-white' : 'border-white/10 bg-white/[.04] text-white/60 hover:bg-white/[.08] hover:text-white')}>
        <Zap className="h-3.5 w-3.5" /><span className="hidden sm:inline">کارها</span>
      </button>
    )} />
  )
}

function MoreMenu({ ws }: { ws: WorkspaceTab }) {
  const { close, setInbox } = useShell()
  const link = () => `${location.origin}${location.pathname}${serialize(useShell.getState())}`
  return (
    <Menu label="بیشتر" items={[
      { label: 'کپی پیوند این نما', icon: <Copy className="h-3.5 w-3.5" />, onSelect: () => void navigator.clipboard?.writeText(link()) },
      { label: 'باز کردن در پنجرهٔ جدید', icon: <ExternalLink className="h-3.5 w-3.5" />, onSelect: () => window.open(link(), '_blank') },
      { label: 'صندوق کارها', onSelect: () => setInbox(true) },
      'sep',
      { label: `بستن ${sectionById(ws.section).title}`, icon: <X className="h-3.5 w-3.5" />, onSelect: () => close(ws.section) },
    ]} trigger={() => (
      <button aria-label="بیشتر" className="flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-white/60 hover:bg-white/[.08] hover:text-white"><MoreHorizontal className="h-[18px] w-[18px]" /></button>
    )} />
  )
}
