import { useMutation, useQuery } from '@tanstack/react-query'
import { CalendarPlus, CheckCircle2, Loader2, PenLine, Scale, Search, Send } from 'lucide-react'
import { useMemo, useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive, useOptions, useRefreshArchive } from '@/api/queries'
import type { AnswerResult, LegalCase } from '@/api/types'
import { AnswerCard } from '@/components/assistant/AnswerCard'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill, Stat } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/segmented'
import { Bar, CaseNo, Chips, KV, Timeline } from '@/components/shared/Bits'
import { GraphView } from '@/components/shared/GraphView'
import { Lessons } from '@/components/shared/Lessons'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'
import { compactRial, date, fa, pct, rial } from '@/lib/format'
import { asText, cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'

/** ۰۳ پرونده‌ها — entries folded into cases, and the case file with its seven tabs. */
export const ROLE_FA: Record<string, string> = {
  khahan: 'خواهان', khande: 'خوانده', vakil_khahan: 'وکیل خواهان', vakil_khande: 'وکیل خوانده', ghazi: 'قاضی', mottaham: 'متهم', shaki: 'شاکی',
  plaintiff: 'خواهان', defendant: 'خوانده', lawyer: 'وکیل', judge: 'قاضی', witness: 'شاهد', expert: 'کارشناس', insurer: 'بیمه‌گر', insured: 'بیمه‌گذار', other: 'سایر',
}
const USED_BY_FA: Record<string, string> = { court: 'دادگاه', plaintiff: 'خواهان', defendant: 'خوانده', judge: 'قاضی', insurer: 'بیمه‌گر', insured: 'بیمه‌گذار', expert: 'کارشناس', lawyer: 'وکیل' }
const ALL = ''

export function CasesView({ ws }: { ws: WorkspaceTab }) {
  const { data, error, refetch } = useArchive()
  if (error) return <LoadError error={error} retry={() => void refetch()} />
  if (!data) return <Skeleton />
  if (ws.active) {
    const c = data.cases.find((x) => x.id === ws.active || x.number === ws.active)
    return c ? <CaseFile c={c} all={data.cases} /> : <Empty title="پرونده پیدا نشد" detail={`«${fa(ws.active)}» در آرشیو نیست — شاید حذف یا ویرایش شده باشد.`} />
  }
  return <CaseList cases={data.cases} tab={ws.tab} query={ws.query ?? ''} />
}

function CaseList({ cases, tab, query }: { cases: LegalCase[]; tab: string; query: string }) {
  const { data: options } = useOptions()
  const { openInner, setQuery } = useShell()
  const [type, setType] = useState(ALL)
  const [line, setLine] = useState(ALL)
  usePublishContext('cases', { filters: Object.fromEntries([type && ['نوع دعوا', type], line && ['رشتهٔ بیمه', line], query && ['جستجو', query]].filter(Boolean) as [string, string][]) })
  const rows = useMemo(() => cases.filter((c) => {
    const r = c.record
    if (tab === 'open' && !(r && r.status && r.status !== 'closed')) return false
    if (tab === 'closed' && r?.status !== 'closed') return false
    if (tab === 'incomplete' && !c.incomplete) return false
    if (type && r?.case_type !== type) return false
    if (line && r?.insurance_line !== line) return false
    if (query) {
      const hay = `${c.number} ${c.title} ${c.subject} ${c.court} ${r?.case_type ?? ''} ${r?.insurance_line ?? ''} ${c.parties.map((p) => p.name).join(' ')} ${c.tags.join(' ')}`
      if (!query.split(/\s+/).every((w) => hay.includes(w))) return false
    }
    return true
  }), [cases, tab, type, line, query])
  const select = 'h-10 rounded-2xl border border-white/10 bg-white/[.04] px-3 text-xs text-white/75 outline-none'
  return (
    <>
      <PageHeader eyebrow="۰۳ · پرونده‌ها" title="پرونده‌ها" summary="هر پرونده، همهٔ مدخل‌هایی است که یک شمارهٔ پرونده دارند — با طرفین، رویدادها، استنادها و وضعیت." right={<Pill>{fa(rows.length)} از {fa(cases.length)}</Pill>} />
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="glass flex min-w-[240px] flex-1 items-center gap-2 rounded-2xl px-3">
          <Search className="h-4 w-4 text-white/35" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="شماره، عنوان، طرف دعوا یا برچسب…" className="h-10 flex-1 bg-transparent text-[13px] outline-none placeholder:text-white/25" />
        </div>
        <select className={select} value={type} onChange={(e) => setType(e.target.value)} aria-label="نوع دعوا"><option value="">همهٔ انواع دعوا</option>{options?.case_types.map((t) => <option key={t}>{t}</option>)}</select>
        <select className={select} value={line} onChange={(e) => setLine(e.target.value)} aria-label="رشتهٔ بیمه"><option value="">همهٔ رشته‌های بیمه</option>{options?.insurance_lines.map((t) => <option key={t}>{t}</option>)}</select>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {rows.slice(0, 200).map((c) => <CaseRow key={c.id} c={c} onOpen={() => openInner(c.id, fa(c.number || c.title.slice(0, 18)))} />)}
      </div>
      {!rows.length && <Empty title="پرونده‌ای با این صافی‌ها نیست" />}
    </>
  )
}

export function CaseRow({ c, onOpen }: { c: LegalCase; onOpen: () => void }) {
  const r = c.record
  return (
    <button onClick={onOpen} className="surface group rounded-3xl p-4 text-start transition hover:-translate-y-0.5 hover:bg-white/[.04]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-[13.5px] font-medium leading-6 text-white/90">{fa(c.title)}</div>
        {c.incomplete ? <Pill tone="warn">ناقص</Pill> : r?.status_fa ? <Pill tone={r.status === 'closed' ? 'neutral' : 'info'}>{r.status_fa}</Pill> : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-white/45">
        <CaseNo value={c.number} />
        {r?.case_type && <span>{r.case_type}</span>}
        {r?.insurance_line && <span>· {r.insurance_line}</span>}
        {r?.claim_amount ? <span>· {compactRial(r.claim_amount)}</span> : null}
      </div>
      <div className="mt-1 truncate text-[11.5px] text-white/40">{fa(c.court)}</div>
      {c.parties.length > 0 && <div className="mt-2 truncate text-[11.5px] text-white/55">{c.parties.slice(0, 3).map((p) => `${ROLE_FA[p.role] ?? p.role}: ${p.name}`).join(' · ')}</div>}
      {c.incomplete && <div className="mt-1 text-[11px] text-amber-200/70">{c.incomplete_reasons.join('، ')}</div>}
    </button>
  )
}

type Tab = 'summary' | 'timeline' | 'ask' | 'docs' | 'similar' | 'status' | 'graph'
const TABS: { id: Tab; label: string }[] = [
  { id: 'summary', label: 'خلاصه' }, { id: 'timeline', label: 'تایم‌لاین' }, { id: 'ask', label: 'پرسش از این پرونده' }, { id: 'docs', label: 'اسناد و مدخل‌ها' },
  { id: 'similar', label: 'پرونده‌های مشابه' }, { id: 'status', label: 'وضعیت و مالی' }, { id: 'graph', label: 'گراف و مستندات' },
]

function CaseFile({ c, all }: { c: LegalCase; all: LegalCase[] }) {
  const [tab, setTab] = useState<Tab>('summary')
  usePublishContext('cases', { entityKind: 'case', entityLabel: c.number ? fa(c.number) : c.title.slice(0, 24), documentIds: c.doc_ids, view: TABS.find((t) => t.id === tab)!.label })
  const r = c.record
  return (
    <>
      <PageHeader eyebrow={`پرونده · ${c.number ? fa(c.number) : 'بدون شماره'}`} title={fa(c.title)} summary={`${fa(c.court)}${c.subject && c.subject !== '—' ? ` · ${c.subject}` : ''}`}
        right={<>{c.incomplete ? <Pill tone="warn">ناقص: {c.incomplete_reasons.join('، ')}</Pill> : <Pill tone="good" dot>کامل</Pill>}{r?.status_fa && <Pill tone="info">{r.status_fa}</Pill>}</>} />
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="نوع دعوا" value={<span className="text-base">{r?.case_type ?? '—'}</span>} />
        <Stat label="رشتهٔ بیمه" value={<span className="text-base">{r?.insurance_line ?? '—'}</span>} />
        <Stat label="مبلغ خواسته" value={<span className="text-base">{compactRial(r?.claim_amount)}</span>} />
        <Stat label="مدخل‌ها · رویدادها" value={`${fa(c.entries.length)} · ${fa(c.events.length)}`} hint={c.last_event_date ? `آخرین: ${fa(c.last_event_date)}` : undefined} />
      </div>
      <div className="mt-5"><Segmented<Tab> layoutId={`case-tab-${c.id}`} value={tab} onChange={setTab} items={TABS} /></div>
      <div className="mt-4">
        {tab === 'summary' && <Summary c={c} />}
        {tab === 'timeline' && <CaseTimeline c={c} />}
        {tab === 'ask' && <AskCase c={c} />}
        {tab === 'docs' && <Docs c={c} />}
        {tab === 'similar' && <Similar c={c} all={all} />}
        {tab === 'status' && <Status c={c} />}
        {tab === 'graph' && <GraphTab c={c} />}
      </div>
    </>
  )
}

function Summary({ c }: { c: LegalCase }) {
  const open = useShell((s) => s.open)
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="px-5 py-3">
        <KV rows={[['شمارهٔ پرونده', <CaseNo value={c.number || null} />], ['موضوع', c.subject], ['مرجع رسیدگی', fa(c.court)], ['تعداد مدخل‌ها', fa(c.entries.length)], ['آخرین رویداد', fa(c.last_event_date ?? '—')]]} />
      </Card>
      <Card>
        <CardHeader title="طرفین" />
        <div className="px-5 pb-4">
          {c.parties.length ? <KV rows={c.parties.map((p) => [ROLE_FA[p.role] ?? p.role, <button onClick={() => open('entities', { tab: /شرکت|سازمان|بانک|صندوق|بیمه|کارخانه|هلدینگ/.test(p.name) ? 'org' : 'person', record: p.name, label: p.name.slice(0, 20) })} className="hover:text-cyan-100">{p.name}</button>])} /> : <div className="text-xs text-white/35">طرفینی استخراج نشده است.</div>}
        </div>
      </Card>
      {c.representation.length > 0 && (
        <Card><CardHeader title="وکالت" /><div className="px-5 pb-4"><KV rows={c.representation.map((r) => [r.lawyer ?? '—', r.client ?? r.for ?? r.party ?? '—'])} /></div></Card>
      )}
      <Card><CardHeader title="برچسب‌ها و موضوعات" /><div className="space-y-3 px-5 pb-5"><Chips tone="teal" items={c.tags} onClick={(t) => open('taxonomy', { query: t })} /><Chips items={c.topics.map((t) => fa(t))} /></div></Card>
    </div>
  )
}

function CaseTimeline({ c }: { c: LegalCase }) {
  const refresh = useRefreshArchive()
  const [form, setForm] = useState({ date: '', title: '', detail: '', reminder: true })
  const [preview, setPreview] = useState(false)
  const add = useMutation({
    mutationFn: () => api.addCaseEvent(c.id, form),
    onSuccess: () => {
      useAssistant.getState().toast({ tone: 'success', title: 'به خط زمان افزوده شد', detail: 'در همین پرونده، «رویدادها» و داشبورد دیده می‌شود.' })
      useAssistant.getState().log({ kind: 'saved', text: `رویداد «${form.title}» به پروندهٔ ${c.number} افزوده شد`, refs: [c.id] })
      setForm({ date: '', title: '', detail: '', reminder: true }); setPreview(false); void refresh()
    },
  })
  const field = 'mt-1 h-10 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-[13px] outline-none focus:border-indigo-300/40'
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_380px]">
      <Card className="p-5">
        <Timeline items={c.events.map((e) => ({ date: e.date, title: fa(asText(e.description ?? e.what ?? e.type) || '—'), detail: e.detail ? fa(e.detail) : undefined, tone: e.source === 'manual' || e.reminder ? 'manual' : 'default', source: e.source === 'manual' ? 'افزوده‌شده' : e.reminder ? 'یادآور' : undefined }))} />
      </Card>
      <Card className="self-start p-5">
        <div className="flex items-center gap-2 text-sm font-medium"><CalendarPlus className="h-4 w-4 text-white/50" /> افزودن رویداد یا یادآور</div>
        <p className="mt-1 text-[11.5px] leading-5 text-white/40">تاریخ را همان‌طور که در پرونده نوشته می‌شود وارد کنید — مثلاً ۱۴۰۳/۰۷/۰۵.</p>
        <label className="mt-3 block text-[11.5px] text-white/45">تاریخ<input className={field} placeholder="۱۴۰۳/۰۷/۰۵" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
        <label className="mt-2 block text-[11.5px] text-white/45">عنوان<input className={field} placeholder="جلسهٔ رسیدگی / مهلت لایحه" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
        <label className="mt-2 block text-[11.5px] text-white/45">توضیح (اختیاری)<textarea rows={2} className={cn(field, 'h-auto py-2')} value={form.detail} onChange={(e) => setForm({ ...form, detail: e.target.value })} /></label>
        <label className="mt-2 flex items-center gap-2 text-[12px] text-white/55"><input type="checkbox" className="accent-amber-300" checked={form.reminder} onChange={(e) => setForm({ ...form, reminder: e.target.checked })} /> این یک یادآور است (کاری که باید انجام شود)</label>
        {preview && (
          <div className="suggested mt-3 rounded-2xl p-3 text-[12px] leading-6 text-violet-50/90">
            افزوده می‌شود: <b>{form.title}</b>{form.date ? ` — ${fa(form.date)}` : ''}{form.reminder ? ' (یادآور)' : ''} به پروندهٔ {fa(c.number)}.
          </div>
        )}
        {add.error && <div className="mt-2 text-[11.5px] text-rose-200/80">{describeError(add.error)}</div>}
        <div className="mt-3 flex gap-2">
          {!preview ? <Button variant="primary" disabled={!form.title.trim()} onClick={() => setPreview(true)}>پیش‌نمایش</Button> : <>
            <Button variant="ghost" onClick={() => setPreview(false)}>ویرایش</Button>
            <Button variant="approve" disabled={add.isPending} onClick={() => add.mutate()}>{add.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} تأیید و افزودن</Button>
          </>}
        </div>
      </Card>
    </div>
  )
}

function AskCase({ c }: { c: LegalCase }) {
  const [q, setQ] = useState('')
  const ask = useMutation({ mutationFn: () => api.ask(q, { document_ids: c.doc_ids }) })
  const result = ask.data ? ({ ...ask.data, intent: 'query' } as AnswerResult) : null
  return (
    <Card className="p-5">
      <p className="text-[12px] text-white/45">پاسخ فقط از اسناد همین پرونده — {fa(c.doc_ids.length)} سند.</p>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate() }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="مثلاً: کارشناس چه نظری داد؟ مهلت لایحه تا کی بود؟" className="h-11 flex-1 rounded-2xl border border-white/10 bg-white/[.04] px-4 text-[13px] outline-none focus:border-indigo-300/40" />
        <Button type="submit" variant="primary" size="lg" disabled={!q.trim() || ask.isPending || !c.doc_ids.length}>{ask.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4 -scale-x-100" />} بپرس</Button>
      </form>
      {!c.doc_ids.length && <div className="mt-3 text-xs text-white/40">سند نمایه‌شده‌ای برای این پرونده نیست.</div>}
      {ask.error && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(ask.error)}</div>}
      {result && (
        <div className="mt-5 space-y-3">
          <div className="whitespace-pre-line text-[13.5px] leading-7 text-white/85">{fa(result.answer ?? '')}</div>
          <AnswerCard result={result} scope={`فقط از اسناد پروندهٔ ${fa(c.number)}`} />
        </div>
      )}
    </Card>
  )
}

function Docs({ c }: { c: LegalCase }) {
  const open = useShell((s) => s.open)
  return (
    <div className="space-y-2.5">
      {c.entries.map((e) => (
        <Card key={e.id} className="flex flex-wrap items-center gap-3 p-4">
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium text-white/85">{fa(e.title || 'بدون عنوان')}</div>
            <div className="mt-0.5 line-clamp-2 text-[12px] leading-6 text-white/45">{fa(e.summary)}</div>
            <div className="mt-1 text-[11px] text-white/30">نوع: {e.kind || '—'} · ثبت: {date(e.created_at)}</div>
          </div>
          <div className="flex gap-2">
            {e.document_id && <Button size="sm" onClick={() => open('documents', { record: e.document_id!, label: 'سند' })}>سند</Button>}
            <Button size="sm" variant="ghost" onClick={() => open('editor', { record: e.id, label: 'ویرایش مدخل' })}><PenLine className="h-3.5 w-3.5" /> ویرایش</Button>
          </div>
        </Card>
      ))}
    </div>
  )
}

function Similar({ c, all }: { c: LegalCase; all: LegalCase[] }) {
  const { openInner } = useShell()
  const graph = useQuery({ queryKey: ['similar', c.record?.id], queryFn: () => api.similarCases(c.record!.id), enabled: !!c.record })
  const shared = all.filter((o) => o.id !== c.id && (c.related_ids.some((id) => o.entries.some((e) => e.id === id || e.document_id === id)) || o.tags.some((t) => c.tags.includes(t)))).slice(0, 8)
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader title="پرونده‌های مشابه از گراف" subtitle="مواد مشترک، طرفین، مرجع و برچسب‌ها — با دلیل هر پیوند" />
        <div className="space-y-2 px-5 pb-5">
          {!c.record && <div className="text-xs text-white/40">این پرونده رکورد ساختاریافته ندارد.</div>}
          {graph.isLoading && <div className="flex items-center gap-2 text-xs text-white/40"><Loader2 className="h-3.5 w-3.5 animate-spin" /> در حال جستجو…</div>}
          {graph.data?.similar.map((s) => (
            <button key={s.id} onClick={() => openInner(s.case_number, fa(s.case_number))} className="block w-full rounded-2xl border border-white/[.06] bg-white/[.02] p-3 text-start hover:bg-white/[.04]">
              <div className="flex items-center justify-between gap-2"><span className="text-[12.5px] text-white/85">{fa(s.title)}</span>{typeof s.score === 'number' && <span className="tnum text-[11px] text-white/40">{pct(Math.min(s.score, 1))}</span>}</div>
              {typeof s.score === 'number' && <div className="mt-1.5"><Bar value={Math.min(s.score, 1)} max={1} tone="violet" /></div>}
              {s.outcome && <div className="mt-1 text-[11px] text-white/45">نتیجه: {fa(s.outcome)}</div>}
              {(s.reasons ?? s.why)?.length ? <div className="mt-1 text-[10.5px] text-white/35">{(s.reasons ?? s.why)!.join(' · ')}</div> : null}
            </button>
          ))}
          {graph.data && <Lessons lessons={graph.data.lessons} />}
          <div className="text-[10.5px] text-white/30">این فهرست تاریخی است، نه پیش‌بینی نتیجهٔ پروندهٔ جاری.</div>
        </div>
      </Card>
      <div className="space-y-5">
        {c.related_links.length > 0 && (
          <Card>
            <CardHeader title="پیوندهای ثبت‌شده در خط لوله" />
            <div className="space-y-2 px-5 pb-5">
              {c.related_links.slice(0, 10).map((l, i) => (
                <div key={i} className="rounded-xl border border-white/[.05] p-2.5">
                  <div className="text-[12.5px] text-white/80">{fa(l.title)}</div>
                  {l.outcome && <div className="text-[11px] text-white/40">نتیجه: {fa(l.outcome)}</div>}
                  {typeof l.score === 'number' && <div className="mt-1"><Bar value={l.score} max={1} /></div>}
                </div>
              ))}
            </div>
          </Card>
        )}
        <Card>
          <CardHeader title="پرونده‌های هم‌موضوع در آرشیو" />
          <div className="space-y-2 px-5 pb-5">
            {shared.map((o) => <CaseRow key={o.id} c={o} onOpen={() => openInner(o.id, fa(o.number || o.title.slice(0, 18)))} />)}
            {!shared.length && <div className="text-xs text-white/40">پروندهٔ هم‌موضوعی یافت نشد.</div>}
          </div>
        </Card>
      </div>
    </div>
  )
}

function Status({ c }: { c: LegalCase }) {
  const r = c.record
  const refresh = useRefreshArchive()
  const [edit, setEdit] = useState<{ status: string; stage: string; outcome: string } | null>(null)
  const save = useMutation({
    mutationFn: () => api.patchCase(r!.id, edit!),
    onSuccess: () => { useAssistant.getState().toast({ tone: 'success', title: 'وضعیت پرونده ذخیره شد' }); useAssistant.getState().log({ kind: 'saved', text: `وضعیت پروندهٔ ${c.number} به‌روز شد`, refs: [r!.id] }); setEdit(null); void refresh() },
  })
  const money = c.entries.flatMap((e) => Object.entries(e.entities ?? {}).filter(([k]) => /amount|مبلغ|value|claim/.test(k)).map(([k, v]) => [k, v] as const))
  if (!r) return <Empty title="این پرونده رکورد ساختاریافته ندارد" detail="شمارهٔ پرونده استخراج نشده است — آن را در «بازبینی انسانی» کامل کنید." />
  const field = 'mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none'
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card className="px-5 py-3">
        <KV rows={[['نوع دعوا', r.case_type ?? '—'], ['رشتهٔ بیمه', r.insurance_line ?? '—'], ['وضعیت', r.status_fa ?? '—'], ['مرحله', r.stage ?? '—'], ['تاریخ طرح', fa(r.filed_date ?? '—')], ['تاریخ رأی', fa(r.decided_date ?? '—')], ['مبلغ خواسته', rial(r.claim_amount)], ['نتیجه', fa(r.outcome ?? '—')]]} />
      </Card>
      <div className="space-y-5">
        <Card className="p-5">
          <div className="flex items-center justify-between"><div className="text-sm font-medium">ویرایش وضعیت</div>{!edit && <Button size="sm" onClick={() => setEdit({ status: r.status ?? '', stage: r.stage ?? '', outcome: r.outcome ?? '' })}><PenLine className="h-3.5 w-3.5" /> ویرایش</Button>}</div>
          {edit && (
            <div className="mt-3 space-y-2">
              <label className="block text-[11px] text-white/45">وضعیت<select className={field} value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>{['open', 'appeal', 'closed', 'pending'].map((s) => <option key={s} value={s}>{({ open: 'جاری', appeal: 'تجدیدنظر', closed: 'مختومه', pending: 'در انتظار' } as Record<string, string>)[s]}</option>)}</select></label>
              <label className="block text-[11px] text-white/45">مرحله<input className={field} value={edit.stage} onChange={(e) => setEdit({ ...edit, stage: e.target.value })} /></label>
              <label className="block text-[11px] text-white/45">نتیجه<input className={field} value={edit.outcome} onChange={(e) => setEdit({ ...edit, outcome: e.target.value })} /></label>
              <div className="suggested rounded-xl p-2.5 text-[11.5px] text-violet-50/85">پیش‌نمایش: {({ open: 'جاری', appeal: 'تجدیدنظر', closed: 'مختومه', pending: 'در انتظار' } as Record<string, string>)[edit.status] ?? edit.status} · {edit.stage || '—'} · {edit.outcome || '—'}</div>
              {save.error && <div className="text-[11.5px] text-rose-200/80">{describeError(save.error)}</div>}
              <div className="flex gap-2"><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>انصراف</Button><Button size="sm" variant="approve" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} تأیید و ذخیره</Button></div>
            </div>
          )}
        </Card>
        {money.length > 0 && <Card className="px-5 py-3"><KV rows={money.map(([k, v]) => [k, rial(asText(v))])} /></Card>}
      </div>
    </div>
  )
}

function GraphTab({ c }: { c: LegalCase }) {
  const open = useShell((s) => s.open)
  const detail = useQuery({ queryKey: ['case', c.record?.id], queryFn: () => api.caseDetail(c.record!.id), enabled: !!c.record })
  const graph = useQuery({ queryKey: ['case-graph', c.record?.id], queryFn: () => api.caseGraph(c.record!.id), enabled: !!c.record })
  if (!c.record) return <Empty title="این پرونده رکورد ساختاریافته ندارد" detail="شمارهٔ پرونده استخراج نشده است." />
  if (!detail.data) return detail.error ? <LoadError error={detail.error} /> : <Skeleton />
  const d = detail.data
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="مستندات قانونی" subtitle={`${fa(d.references.length)} استناد`} />
          <div className="space-y-2 px-5 pb-5">
            {d.references.map((ref) => (
              <button key={ref.id} onClick={() => open('laws', { record: ref.id, label: `مادهٔ ${fa(ref.article_no ?? '')}` })} className="block w-full rounded-2xl border border-amber-300/10 bg-amber-300/[.03] p-3 text-start hover:bg-amber-300/[.06]">
                <div className="flex items-center gap-2 text-[12.5px] text-white/85"><Scale className="h-3.5 w-3.5 text-amber-200/70" /> {fa(ref.cite)}</div>
                {ref.context && <div className="mt-0.5 text-[11.5px] text-white/45">{ref.context}</div>}
                {ref.used_by && <div className="mt-0.5 text-[10.5px] text-white/30">استنادکننده: {USED_BY_FA[ref.used_by] ?? ref.used_by}</div>}
              </button>
            ))}
            {!d.references.length && <div className="text-xs text-white/40">استنادی ثبت نشده است.</div>}
          </div>
        </Card>
        <Card>
          <CardHeader title="طرفین (رکوردها)" />
          <div className="space-y-1.5 px-5 pb-5">
            {d.parties.map((p, i) => (
              <button key={`${p.id}-${i}`} onClick={() => open('entities', { tab: p.type, record: p.id, label: p.name.slice(0, 20) })} className="flex w-full items-center justify-between rounded-xl border border-white/[.05] px-3 py-2 text-start text-[12.5px] hover:bg-white/[.03]">
                <span className="text-white/80">{p.name}</span><span className="text-[11px] text-white/40">{p.role_fa} · {p.type === 'org' ? 'سازمان' : 'شخص'}</span>
              </button>
            ))}
          </div>
        </Card>
      </div>
      <Card>
        <CardHeader title="گراف پرونده" subtitle="روی هر گره بزنید تا باز شود" />
        <div className="px-5 pb-5">
          {graph.data ? <GraphView graph={graph.data} focus={c.record.id} onNode={(n) => {
            if (n.type === 'case') open('cases', { record: String((n as Record<string, unknown>).case_number ?? n.id), label: fa(String((n as Record<string, unknown>).case_number ?? '')) })
            else if (n.type === 'law') open('laws', { record: n.id })
            else if (n.type === 'person' || n.type === 'org') open('entities', { tab: n.type, record: n.id, label: String(n.label).slice(0, 20) })
          }} /> : graph.error ? <LoadError error={graph.error} /> : <Skeleton />}
        </div>
      </Card>
    </div>
  )
}
