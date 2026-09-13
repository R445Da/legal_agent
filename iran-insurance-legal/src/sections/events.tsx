import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useArchive } from '@/api/queries'
import { fa } from '@/lib/format'
import { asText } from '@/lib/utils'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Card, Empty, Pill } from '@/components/ui/misc'
import { CaseNo } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/** ۰۴ رویدادها — every event across every case, newest first, on one timeline. */
export function EventsView(_: { ws: WorkspaceTab }) {
  const { data, error, refetch } = useArchive()
  const open = useShell((s) => s.open)
  const [q, setQ] = useState('')
  const [reminders, setReminders] = useState(false)
  usePublishContext('events', { filters: q ? { جستجو: q } : undefined })
  const events = useMemo(() => (data?.events ?? []).filter((e) => {
    if (reminders && !(e.reminder || e.source === 'manual')) return false
    if (!q.trim()) return true
    const hay = `${asText(e.description ?? e.what ?? e.type)} ${e.detail ?? ''} ${e.case_title} ${e.case_number}`
    return q.trim().split(/\s+/).every((w) => hay.includes(w))
  }), [data, q, reminders])
  if (error) return <LoadError error={error} retry={() => void refetch()} />
  if (!data) return <Skeleton />

  // Group by Solar year/month (the dates are already Persian strings: ۱۴۰۳/۰۷/۰۵).
  const groups: [string, typeof events][] = []
  for (const e of events.slice(0, 400)) {
    const key = (e.date ?? '—').slice(0, 7)
    const last = groups.at(-1)
    if (last && last[0] === key) last[1].push(e); else groups.push([key, [e]])
  }
  return (
    <>
      <PageHeader eyebrow="۰۴ · رویدادها" title="رویدادها" summary="همهٔ رویدادهای استخراج‌شده و افزوده‌شده از تمام پرونده‌ها، از جدید به قدیم." right={<Pill>{fa(events.length)} رویداد</Pill>} />
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="glass flex min-w-[240px] flex-1 items-center gap-2 rounded-2xl px-3">
          <Search className="h-4 w-4 text-white/35" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در رویدادها…" className="h-10 flex-1 bg-transparent text-[13px] outline-none placeholder:text-white/25" />
        </div>
        <label className="flex h-10 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.04] px-3 text-xs text-white/60"><input type="checkbox" className="accent-amber-300" checked={reminders} onChange={(e) => setReminders(e.target.checked)} /> فقط یادآورها و افزوده‌ها</label>
      </div>
      {!events.length ? <Empty title="رویدادی یافت نشد" /> : (
        <div className="mt-5 space-y-6">
          {groups.map(([month, list]) => (
            <section key={month}>
              <div className="tnum mb-2 text-[12px] font-medium text-white/40">{fa(month)}</div>
              <Card className="divide-y divide-white/[.05]">
                {list.map((e, i) => (
                  <button key={`${e.entry_id}-${i}`} onClick={() => open('cases', { record: e.case_id, label: fa(e.case_number || e.case_title.slice(0, 16)) })} className="flex w-full items-start gap-4 px-5 py-3 text-start transition hover:bg-white/[.025]">
                    <div className="tnum w-24 shrink-0 pt-0.5 text-[12px] text-white/50">{fa(e.date ?? '—')}</div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] leading-6 text-white/85">{fa(asText(e.description ?? e.what ?? e.type) || '—')}{(e.reminder || e.source === 'manual') && <span className="ms-2 text-amber-300">⏳</span>}</div>
                      {e.detail && <div className="text-[11.5px] text-white/40">{fa(e.detail)}</div>}
                      <div className="mt-0.5 flex items-center gap-2 truncate text-[11px] text-white/35"><CaseNo value={e.case_number || null} /> <span className="truncate">{fa(e.case_title)}</span></div>
                    </div>
                  </button>
                ))}
              </Card>
            </section>
          ))}
        </div>
      )}
    </>
  )
}
