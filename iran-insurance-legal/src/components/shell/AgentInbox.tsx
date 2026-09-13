import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, CircleSlash, ClipboardCheck, GitBranch, History, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '@/api/endpoints'
import { useArchive } from '@/api/queries'
import type { EntryRun } from '@/api/types'
import type { Activity } from '@/assistant/types'
import { ago, fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { useShell } from '@/state/shell'
import { RunCard } from '@/components/assistant/RunCard'
import { Segmented } from '@/components/ui/segmented'
import { Button } from '@/components/ui/button'
import { Empty, Pill } from '@/components/ui/misc'

type Tab = 'approvals' | 'review' | 'failed' | 'ci' | 'activity'

/** صندوق کارها — everything that needs a human: gated filings, the review queue, failed runs, CI, and the activity timeline. */
export function AgentInbox() {
  const { inboxOpen, setInbox, open } = useShell()
  const local = useAssistant((s) => s.runs)
  const activity = useAssistant((s) => s.activity)
  const { data } = useArchive()
  const server = useQuery({ queryKey: ['runs'], queryFn: () => api.runs(40), enabled: inboxOpen })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: api.integrations, enabled: inboxOpen, retry: false })
  const [tab, setTab] = useState<Tab>('approvals')

  const runs = useMemo(() => {
    const byId = new Map<string, EntryRun>()
    server.data?.runs.forEach((r) => byId.set(r.id, r))
    Object.values(local).forEach((r) => byId.set(r.id, r))
    return [...byId.values()].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
  }, [server.data, local])
  const awaiting = runs.filter((r) => r.status === 'awaiting_input')
  const failed = runs.filter((r) => r.status === 'failed')
  const queue = data?.review_queue ?? []
  const ciRuns = (integrations.data?.ci_runs ?? []) as { id?: string; name?: string; title?: string; status?: string; conclusion?: string; branch?: string }[]


  return (
    <AnimatePresence>
      {inboxOpen && (
        <>
          <motion.div className="fixed inset-0 z-50 bg-black/40" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setInbox(false)} />
          <motion.aside role="dialog" aria-label="صندوق کارها" initial={{ x: '-100%' }} animate={{ x: 0 }} exit={{ x: '-100%' }} transition={{ type: 'spring', stiffness: 380, damping: 38 }}
            className="fixed inset-y-0 end-0 z-50 flex w-full max-w-[520px] flex-col border-s border-white/[.07] bg-ink-850/95 backdrop-blur-2xl">
            <header className="flex items-center justify-between px-5 pb-3 pt-5">
              <div>
                <div className="text-sm font-semibold">صندوق کارها</div>
                <div className="text-[11px] text-white/35">هر آنچه به تصمیم شما نیاز دارد</div>
              </div>
              <button onClick={() => setInbox(false)} aria-label="بستن" className="flex h-9 w-9 items-center justify-center rounded-xl text-white/45 hover:bg-white/[.06] hover:text-white"><X className="h-4 w-4" /></button>
            </header>
            <div className="px-5 pb-3">
              <Segmented<Tab> layoutId="inbox-tab" value={tab} onChange={setTab} counts={{ approvals: awaiting.length, review: queue.length, failed: failed.length }}
                items={[{ id: 'approvals', label: 'در انتظار تأیید' }, { id: 'review', label: 'بازبینی' }, { id: 'failed', label: 'ناموفق' }, { id: 'ci', label: 'CI' }, { id: 'activity', label: 'فعالیت' }]} />
            </div>
            <div className="flex-1 space-y-3 overflow-y-auto px-5 pb-8">
              {tab === 'approvals' && (awaiting.length ? awaiting.map((r) => <RunCard key={r.id} runId={r.id} compact />) : <Empty icon={<CheckCircle2 className="h-5 w-5" />} title="چیزی منتظر تأیید شما نیست" detail="ثبت‌هایی که در گامی برای تأیید ایستاده‌اند اینجا جمع می‌شوند." />)}
              {tab === 'review' && (queue.length ? queue.map((c) => (
                <div key={c.id} className="surface rounded-2xl p-4">
                  <div className="flex items-start gap-3">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-rose-300/20 bg-rose-300/10 text-rose-200"><ClipboardCheck className="h-4 w-4" /></span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-white/85">{fa(c.title)}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">{c.incomplete_reasons.map((r) => <Pill key={r} tone="warn">{r}</Pill>)}</div>
                      <Button size="sm" className="mt-3" onClick={() => { setInbox(false); open('review', { origin: 'tab' }) }}>بازبینی</Button>
                    </div>
                  </div>
                </div>
              )) : <Empty icon={<CheckCircle2 className="h-5 w-5" />} title="صف بازبینی خالی است" />)}
              {tab === 'failed' && (failed.length ? failed.map((r) => <RunCard key={r.id} runId={r.id} compact />) : <Empty icon={<CircleSlash className="h-5 w-5" />} title="اجرای ناموفقی نیست" detail="اجراهای ناموفق اینجا نگه داشته می‌شوند تا چیزی بی‌صدا گم نشود." />)}
              {tab === 'ci' && (ciRuns.length ? ciRuns.map((r, i) => (
                <div key={r.id ?? i} className="surface flex items-center gap-3 rounded-2xl p-3.5">
                  <GitBranch className="h-4 w-4 text-white/40" />
                  <div className="min-w-0 flex-1 text-[12.5px] text-white/80">{r.title ?? r.name ?? r.id}<div className="text-[11px] text-white/35">{r.branch}</div></div>
                  <Pill tone={r.conclusion === 'success' ? 'good' : r.conclusion === 'failure' ? 'bad' : 'info'}>{r.conclusion ?? r.status ?? '—'}</Pill>
                </div>
              )) : <Empty icon={<GitBranch className="h-5 w-5" />} title="رویدادی از CI نرسیده است" detail="«python -m scripts.replay_ci» یک اجرا را بازپخش می‌کند." />)}
              {tab === 'activity' && <ActivityTimeline items={activity} />}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

const ACT_TONE: Record<Activity['kind'], string> = {
  routed: 'bg-cyan-300', answered: 'bg-indigo-300', filing: 'bg-violet-300', gate: 'bg-amber-300', committed: 'bg-emerald-300',
  abandoned: 'bg-white/40', undone: 'bg-amber-300', failed: 'bg-rose-300', saved: 'bg-emerald-300', deleted: 'bg-rose-300',
}
const ACT_FA: Record<Activity['kind'], string> = { routed: 'هدایت', answered: 'پاسخ', filing: 'ثبت', gate: 'تأیید', committed: 'ثبت نهایی', abandoned: 'توقف', undone: 'برگرداندن', failed: 'خطا', saved: 'ذخیره', deleted: 'حذف' }

/** Every meaningful assistant action, as a user-facing timeline. */
export function ActivityTimeline({ items }: { items: Activity[] }) {
  if (!items.length) return <Empty icon={<History className="h-5 w-5" />} title="هنوز فعالیتی ثبت نشده" detail="هر کاری دستیار انجام دهد اینجا ثبت می‌شود." />
  return (
    <ol className="relative ms-2 space-y-4 border-s border-white/[.07] ps-5 pt-1">
      {items.map((a) => (
        <li key={a.id} className="relative">
          <span className={cn('absolute -start-[25px] top-2 h-2 w-2 rounded-full ring-4 ring-ink-850', ACT_TONE[a.kind])} />
          <div className="text-[12.5px] leading-6 text-white/75">{a.text}</div>
          <div className="mt-0.5 text-[10.5px] text-white/30">{ACT_FA[a.kind]} · {ago(a.at)}</div>
        </li>
      ))}
    </ol>
  )
}
