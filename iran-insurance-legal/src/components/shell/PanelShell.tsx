import { motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import { useArchive } from '@/api/queries'
import { useAssistant } from '@/state/assistant'
import { useShell } from '@/state/shell'
import { GROUPS, SECTIONS } from '@/sections/registry'
import { AppCard } from '@/components/panel/AppCard'
import { AIOrb } from '@/components/assistant/AIOrb'
import { InboxButton, PaletteButton } from './TopActions'

/** پیشخوان بخش‌ها — "What can I operate?" Every Streamlit section as an app. */
export function PanelShell() {
  const { goHome, open, tabs } = useShell()
  const { data } = useArchive()
  const orb = useAssistant((s) => s.orb)
  let index = 0
  return (
    <div className="mesh grid-bg min-h-full">
      <header className="flex items-center justify-between px-5 py-5 lg:px-10">
        <div className="flex items-center gap-3">
          <button onClick={goHome} aria-label="بازگشت به دستیار" className="flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-white/70 hover:bg-white/[.08] hover:text-white"><ArrowRight className="h-[18px] w-[18px]" /></button>
          <div>
            <div className="text-sm font-semibold">پیشخوان بخش‌ها</div>
            <div className="text-[11px] text-white/35">فضای برنامه‌های بیمه ایران حقوقی</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <PaletteButton label="مرکز فرمان" />
          <InboxButton />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 pb-16 lg:px-10">
        <div className="flex flex-col gap-6 pb-6 pt-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-[12px] font-medium text-white/30">فضای کار</div>
            <h2 className="mt-2 text-balance text-3xl font-extrabold tracking-tight sm:text-4xl">هر آنچه دستیار می‌تواند انجام دهد</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-white/40">هر بخش یک فضای کار متمرکز است. دستیار حقوقی در همهٔ بخش‌ها همراه شماست و زمینهٔ صفحه را می‌داند.</p>
          </div>
          <motion.button layoutId="assistant-orb" onClick={goHome} className="glass flex items-center gap-3 self-start rounded-full py-2 pe-4 ps-2 text-start sm:self-auto">
            <AIOrb state={orb} size="sm" />
            <span className="text-xs text-white/60">به‌جای آن از دستیار بپرسید</span>
          </motion.button>
        </div>
        <div className="space-y-9">
          {GROUPS.map((g) => (
            <section key={g.id}>
              <div className="mb-3 flex items-baseline gap-3"><h3 className="text-sm font-semibold text-white/80">{g.title}</h3><span className="text-[11px] text-white/30">{g.hint}</span></div>
              <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-4">
                {SECTIONS.filter((s) => s.group === g.id).map((s) => (
                  <AppCard key={s.id} s={s} state={data} index={index++} open={tabs.some((t) => t.section === s.id)} onOpen={() => open(s.id, { origin: 'card' })} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </main>
    </div>
  )
}
