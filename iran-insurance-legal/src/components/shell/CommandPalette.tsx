import { Command } from 'cmdk'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, Clock, FilePlus2, FolderKanban, House, LayoutGrid, RefreshCw, Scale, Sparkles, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useArchive, useRefreshArchive } from '@/api/queries'
import { ask } from '@/assistant/runtime'
import { fa } from '@/lib/format'
import { useAssistant } from '@/state/assistant'
import { useShell } from '@/state/shell'
import { SECTIONS, sectionById } from '@/sections/registry'
import { Kbd } from '@/components/ui/misc'

/** ⌘K / Ctrl+K — sections, cases, laws, people, actions and recent work. Anything else goes to the assistant. */
export function CommandPalette() {
  const { paletteOpen, setPalette, open, goHome, goPanel, tabs } = useShell()
  const activity = useAssistant((s) => s.activity)
  const { data } = useArchive()
  const refresh = useRefreshArchive()
  const [q, setQ] = useState('')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(!useShell.getState().paletteOpen) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setPalette])
  useEffect(() => { if (!paletteOpen) setQ('') }, [paletteOpen])

  const run = (fn: () => void) => { setPalette(false); fn() }
  const item = 'flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] text-white/70 data-[selected=true]:bg-white/[.07] data-[selected=true]:text-white'
  const group = '[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-3 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-white/30'

  return (
    <AnimatePresence>
      {paletteOpen && (
        <motion.div className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 px-3 pt-[12vh] backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && setPalette(false)}>
          <motion.div initial={{ opacity: 0, y: -10, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8, scale: 0.98 }} transition={{ type: 'spring', stiffness: 420, damping: 34 }} className="w-full max-w-xl">
            <Command label="مرکز فرمان" className="glass overflow-hidden rounded-3xl" loop filter={paletteFilter} onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); setPalette(false) } }}>
              <div className="flex items-center gap-3 border-b border-white/[.06] px-4">
                <Sparkles className="h-4 w-4 text-indigo-200/70" />
                <Command.Input autoFocus value={q} onValueChange={setQ} placeholder="بخش، پرونده، ماده، شخص یا کار — یا از دستیار بپرسید…" className="h-14 flex-1 bg-transparent text-sm outline-none placeholder:text-white/30" />
                <Kbd>Esc</Kbd>
              </div>
              <Command.List className="max-h-[56vh] overflow-y-auto p-2">
                <Command.Empty className="px-3 py-6 text-center text-xs text-white/40">موردی نیست — Enter را بزنید تا از دستیار بپرسید.</Command.Empty>
                {q.trim() && (
                  <Command.Group heading="پرسش از دستیار" className={group} forceMount>
                    <Command.Item value={`ask ${q}`} forceMount onSelect={() => run(() => void ask(q, useShell.getState().layer === 'home' ? 'home' : 'palette'))} className={item}>
                      <Sparkles className="h-4 w-4 text-indigo-200" /> <span className="flex-1 truncate">«{q}»</span> <ArrowLeft className="h-3.5 w-3.5 text-white/30" />
                    </Command.Item>
                  </Command.Group>
                )}
                <Command.Group heading="رفتن به" className={group}>
                  <Command.Item value="دستیار خانه home" onSelect={() => run(goHome)} className={item}><House className="h-4 w-4 text-white/40" /> ۰۱ · دستیار پرونده</Command.Item>
                  <Command.Item value="پیشخوان بخش‌ها panel" onSelect={() => run(goPanel)} className={item}><LayoutGrid className="h-4 w-4 text-white/40" /> پیشخوان بخش‌ها</Command.Item>
                  {SECTIONS.flatMap((s) => [
                    <Command.Item key={s.id} value={`${s.num} ${s.title} ${s.description} ${s.id}`} onSelect={() => run(() => open(s.id, { origin: 'tab' }))} className={item}><s.icon className="h-4 w-4 text-white/40" /><span className="tnum w-6 text-white/30">{s.num}</span> {s.title} <span className="ms-auto truncate text-[11px] text-white/30">{s.description}</span></Command.Item>,
                    ...s.tabs.slice(1).map((t) => <Command.Item key={`${s.id}-${t.id}`} value={`${s.title} ${t.label}`} onSelect={() => run(() => open(s.id, { tab: t.id, origin: 'tab' }))} className={item}><span className="w-4" /> <span className="text-white/40">{s.title} ›</span> {t.label}</Command.Item>),
                  ])}
                </Command.Group>
                <Command.Group heading="کارها" className={group}>
                  <Command.Item value="ثبت مطلب جدید پرونده جدید" onSelect={() => run(() => open('ingest', { tab: 'structured' }))} className={item}><FilePlus2 className="h-4 w-4 text-violet-300" /> ثبت مطلب جدید</Command.Item>
                  <Command.Item value="گفتگوی جدید" onSelect={() => run(() => { useAssistant.getState().clear(); goHome() })} className={item}><Sparkles className="h-4 w-4 text-violet-300" /> گفتگوی جدید</Command.Item>
                  <Command.Item value="بازخوانی آرشیو refresh" onSelect={() => run(() => void refresh())} className={item}><RefreshCw className="h-4 w-4 text-white/40" /> بازخوانی آرشیو</Command.Item>
                </Command.Group>
                {data && (
                  <Command.Group heading="پرونده‌ها" className={group}>
                    {data.cases.slice(0, 400).map((c) => (
                      <Command.Item key={c.id} value={`${c.number} ${c.title} ${c.record?.case_type ?? ''} ${c.parties.map((p) => p.name).join(' ')}`} onSelect={() => run(() => open('cases', { record: c.id, label: fa(c.number || c.title.slice(0, 16)), origin: 'tab' }))} className={item}>
                        <FolderKanban className="h-4 w-4 text-cyan-200/60" /> <span className="ltr font-mono text-[11px] text-cyan-100/80">{fa(c.number || '—')}</span> <span className="min-w-0 truncate text-white/60">{fa(c.title)}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                {data && (
                  <Command.Group heading="قوانین" className={group}>
                    {data.law_titles.map((l) => (
                      <Command.Item key={l.law_title} value={`قانون ${l.law_title}`} onSelect={() => run(() => open('laws', { tab: 'browse', query: l.law_title, origin: 'tab' }))} className={item}><Scale className="h-4 w-4 text-amber-200/60" /> <span className="truncate">{l.law_title}</span> <span className="ms-auto text-[11px] text-white/30">{fa(l.articles)} ماده</span></Command.Item>
                    ))}
                  </Command.Group>
                )}
                {data && (
                  <Command.Group heading="اشخاص پرتکرار" className={group}>
                    {Array.from(new Set(data.cases.flatMap((c) => c.parties.map((p) => p.name)))).slice(0, 60).map((name) => (
                      <Command.Item key={name} value={`شخص ${name}`} onSelect={() => run(() => open('entities', { tab: /شرکت|سازمان|بانک|صندوق|بیمه|دانشگاه|کارخانه|هلدینگ/.test(name) ? 'org' : 'person', record: name, label: name.slice(0, 20), origin: 'tab' }))} className={item}><Users className="h-4 w-4 text-violet-200/60" /> {name}</Command.Item>
                    ))}
                  </Command.Group>
                )}
                {(tabs.length > 0 || activity.length > 0) && (
                  <Command.Group heading="اخیر" className={group}>
                    {tabs.map((t) => <Command.Item key={`open-${t.section}`} value={`بخش باز ${sectionById(t.section).title}`} onSelect={() => run(() => open(t.section, { origin: 'tab' }))} className={item}><Clock className="h-4 w-4 text-white/35" /> {sectionById(t.section).title} <span className="text-white/35">· باز</span></Command.Item>)}
                    {activity.slice(0, 5).map((a) => <Command.Item key={a.id} value={`اخیر ${a.text}`} onSelect={() => run(() => useShell.getState().setInbox(true))} className={item}><Clock className="h-4 w-4 text-white/35" /> <span className="truncate">{a.text}</span></Command.Item>)}
                  </Command.Group>
                )}
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Every typed word must appear in the item (Persian letters folded). */
function paletteFilter(value: string, search: string) {
  const f = (s: string) => s.toLowerCase().replace(/[يى]/g, 'ی').replace(/ك/g, 'ک').replace(/‌/g, ' ').replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
  const v = f(value)
  const words = f(search).split(/\s+/).filter(Boolean)
  if (!words.length) return 1
  if (v.startsWith('ask ')) return 0.5
  return words.every((w) => v.includes(w)) ? 1 : 0
}
