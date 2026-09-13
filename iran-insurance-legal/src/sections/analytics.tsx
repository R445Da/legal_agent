import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2, Send } from 'lucide-react'
import { useState } from 'react'
import { Bar as RBar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive } from '@/api/queries'
import type { AnswerResult, NamedCount } from '@/api/types'
import { compactRial, fa } from '@/lib/format'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { AnswerCard } from '@/components/assistant/AnswerCard'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Stat } from '@/components/ui/misc'
import { Bar } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'
import { axis, faTick, tooltipStyle } from '@/components/shared/chart'

/**
 * ۱۱ آمار آرشیو — the half of the system vector search cannot do: counts over
 * the structured records. Every name opens its profile; every type its cases.
 */
export function AnalyticsView({ ws }: { ws: WorkspaceTab }) {
  usePublishContext('analytics', { view: undefined })
  if (ws.tab === 'people') return <People />
  if (ws.tab === 'ask') return <AskStats />
  return <Overview />
}

function Ranked({ title, rows, onClick, tone = 'cyan' }: { title: string; rows: NamedCount[]; onClick?: (name: string) => void; tone?: 'cyan' | 'violet' | 'amber' | 'emerald' }) {
  const max = Math.max(...rows.map((r) => r.count), 1)
  return (
    <Card>
      <CardHeader title={title} />
      <ul className="space-y-2.5 px-5 pb-5">
        {rows.slice(0, 10).map((r) => (
          <li key={r.name}>
            <button disabled={!onClick} onClick={() => onClick?.(r.name)} className="w-full text-start disabled:cursor-default">
              <div className="mb-1 flex justify-between gap-3 text-[12px]"><span className="truncate text-white/75">{fa((r as NamedCount & { name_fa?: string }).name_fa ?? r.name)}</span><span className="tnum text-white/45">{fa(r.count)}</span></div>
              <Bar value={r.count} max={max} tone={tone} />
            </button>
          </li>
        ))}
        {!rows.length && <li className="text-xs text-white/35">داده‌ای نیست.</li>}
      </ul>
    </Card>
  )
}

function Overview() {
  const { data, error } = useArchive()
  const open = useShell((s) => s.open)
  if (error) return <LoadError error={error} />
  if (!data) return <Skeleton />
  const a = data.archive
  const months = ((a.by_month as [string, number][] | undefined) ?? []).map(([m, n]) => ({ month: m, count: n }))
  const topLaws = ((a.top_laws as { law: string; article: string; count: number }[] | undefined) ?? []).map((l) => ({ name: `مادهٔ ${l.article} ${l.law}`, count: l.count }))
  return (
    <>
      <PageHeader eyebrow="۱۱ · آمار آرشیو" title="آمار بایگانی پرونده‌ها" summary="روی هر نوع دعوا یا رشته بزنید تا پرونده‌های مرتبطش باز شود." />
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="پرونده‌ها" value={fa(a.cases)} />
        <Stat label="مجموع خواسته" value={<span className="text-lg">{compactRial(a.claim_total)}</span>} />
        <Stat label="میانگین خواسته" value={<span className="text-lg">{compactRial(a.claim_avg)}</span>} />
        <Stat label="استنادها" value={fa(a.citations)} hint={`به ${fa(a.laws)} ماده`} />
      </div>
      {months.length > 0 && (
        <Card className="mt-5">
          <CardHeader title="پرونده‌ها در طول زمان" subtitle="بر اساس ماه طرح دعوا" />
          <div className="h-56 px-2 pb-3" dir="ltr">
            <ResponsiveContainer>
              <BarChart data={months}>
                <CartesianGrid vertical={false} stroke="rgba(255,255,255,.04)" />
                <XAxis dataKey="month" {...axis} tickFormatter={faTick} interval="preserveStartEnd" />
                <YAxis width={28} {...axis} tickFormatter={faTick} allowDecimals={false} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fa(String(l))} formatter={(v) => [fa(Number(v)), 'پرونده']} cursor={{ fill: 'rgba(255,255,255,.03)' }} />
                <RBar dataKey="count" fill="#67e8f9" fillOpacity={0.7} radius={[5, 5, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}
      <div className="mt-5 grid gap-5 lg:grid-cols-2 xl:grid-cols-3">
        <Ranked title="بر اساس نوع دعوا" rows={a.by_type} onClick={(n) => open('cases', { tab: 'all', query: n })} />
        <Ranked title="بر اساس رشتهٔ بیمه" rows={a.by_line ?? []} tone="emerald" onClick={(n) => open('cases', { tab: 'all', query: n })} />
        <Ranked title="بر اساس وضعیت" rows={a.by_status ?? []} tone="violet" />
        <Ranked title="بر اساس مرجع رسیدگی" rows={a.by_court ?? []} tone="amber" onClick={(n) => open('cases', { tab: 'all', query: n })} />
        <Ranked title="پراستنادترین مواد" rows={topLaws} tone="amber" onClick={() => open('laws')} />
        <Ranked title="برچسب‌ها" rows={data.tags.map((t) => ({ name: t.tag, count: t.cases }))} onClick={(n) => open('taxonomy', { query: n })} />
      </div>
    </>
  )
}

function People() {
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.stats })
  const open = useShell((s) => s.open)
  if (stats.error) return <LoadError error={stats.error} />
  if (!stats.data) return <Skeleton />
  const s = stats.data as Record<string, NamedCount[] | number>
  const list = (k: string) => (Array.isArray(s[k]) ? (s[k] as NamedCount[]) : [])
  return (
    <>
      <PageHeader eyebrow="۱۱ · آمار آرشیو" title="اشخاص، وکلا و موضوعات" summary="شمارش روی مدخل‌های ساختاریافته — نام‌ها با حذف عنوان‌ها یکی شده‌اند. روی هر نام بزنید تا پروفایلش باز شود." />
      <div className="mt-6 grid grid-cols-3 gap-3"><Stat label="اسناد" value={fa(Number(s.documents))} /><Stat label="مدخل‌ها" value={fa(Number(s.entries))} /><Stat label="قطعه‌ها" value={fa(Number(s.chunks))} /></div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Ranked title="وکلا" rows={list('lawyers')} tone="violet" onClick={(n) => open('entities', { tab: 'person', record: n, label: n.slice(0, 20) })} />
        <Ranked title="اشخاص" rows={list('people')} tone="violet" onClick={(n) => open('entities', { tab: 'person', record: n, label: n.slice(0, 20) })} />
        <Ranked title="سازمان‌ها" rows={list('orgs')} tone="emerald" onClick={(n) => open('entities', { tab: 'org', record: n, label: n.slice(0, 20) })} />
        <Ranked title="موضوعات" rows={list('topics')} onClick={(n) => open('cases', { tab: 'all', query: n.split(/[،,]/)[0] })} />
      </div>
    </>
  )
}

function AskStats() {
  const [q, setQ] = useState('')
  const ask = useMutation({ mutationFn: () => api.assistant(q, 'analytics') })
  return (
    <>
      <PageHeader eyebrow="۱۱ · آمار آرشیو" title="پرسش دربارهٔ آرشیو" summary="شمارش با SQL روی مدخل‌ها انجام می‌شود، بدون مدل؛ فقط خلاصهٔ زبانی از مدل می‌آید." />
      <Card className="mt-6 p-5">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate() }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="چند پرونده شخص ثالث داریم؟" className="h-11 flex-1 rounded-2xl border border-white/10 bg-white/[.04] px-4 text-[13px] outline-none" />
          <Button type="submit" variant="primary" size="lg" disabled={!q.trim() || ask.isPending}>{ask.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4 -scale-x-100" />} پرسش</Button>
        </form>
        {ask.error && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(ask.error)}</div>}
        {ask.data && (
          <div className="mt-5 space-y-3">
            <div className="whitespace-pre-line text-[14px] leading-8 text-white/85">{fa(ask.data.summary ?? ask.data.answer ?? '')}</div>
            <AnswerCard result={ask.data as AnswerResult} />
            <details className="text-[11.5px] text-white/40"><summary className="cursor-pointer">دادهٔ خام</summary><pre className="ltr mt-2 max-h-72 overflow-auto rounded-xl bg-black/30 p-3 text-[11px] text-white/60">{JSON.stringify(ask.data.stats, null, 2)}</pre></details>
          </div>
        )}
      </Card>
    </>
  )
}
