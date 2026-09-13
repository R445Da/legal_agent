import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, FolderOpen, Loader2, Scale, Search } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive, useRefreshArchive } from '@/api/queries'
import type { LawArticle } from '@/api/types'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill } from '@/components/ui/misc'
import { Chips } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

const PAGE = 40

/** ۱۵ قوانین و مستندات — statute articles, آیین‌نامه clauses and the cases that cite them. */
export function LawsView({ ws }: { ws: WorkspaceTab }) {
  if (ws.active) return <Article id={ws.active} />
  if (ws.tab === 'search') return <LawSearch />
  if (ws.tab === 'add') return <AddLaw />
  return <Browse title={ws.query ?? ''} />
}

function Browse({ title }: { title: string }) {
  const { data: state } = useArchive()
  const { setQuery, openInner } = useShell()
  const laws = useQuery({ queryKey: ['laws', title], queryFn: () => api.laws({ law_title: title || undefined }) })
  usePublishContext('laws', { filters: title ? { قانون: title } : undefined })
  const titles = state?.law_titles ?? laws.data?.titles ?? []
  const articles = (laws.data?.items ?? []).filter((a) => a.kind !== 'stub')
  const stubs = (laws.data?.items ?? []).filter((a) => a.kind === 'stub')
  return (
    <>
      <PageHeader eyebrow="۱۵ · قوانین و مستندات" title="قوانین و مستندات" summary="مواد قانونی، آیین‌نامه‌ها و آرای وحدت رویه‌ای که پرونده‌های آرشیو به آن‌ها استناد کرده‌اند." />
      <div className="mt-6 grid gap-5 lg:grid-cols-[300px_1fr]">
        <Card className="self-start p-2">
          <button onClick={() => setQuery('')} className={cn('flex w-full items-center justify-between rounded-2xl px-3 py-2.5 text-start text-[12.5px]', !title ? 'bg-white/[.08] text-white' : 'text-white/60 hover:bg-white/[.04]')}>
            <span>همهٔ قوانین</span><span className="tnum text-[11px] text-white/40">{fa(titles.reduce((s, t) => s + t.articles, 0))}</span>
          </button>
          {titles.map((t) => (
            <button key={t.law_title} onClick={() => setQuery(t.law_title)} className={cn('flex w-full items-start justify-between gap-2 rounded-2xl px-3 py-2.5 text-start text-[12.5px] leading-6', t.law_title === title ? 'bg-white/[.08] text-white' : 'text-white/60 hover:bg-white/[.04]')}>
              <span className="min-w-0">{t.law_title}{t.law_year ? <span className="text-white/35"> ({fa(t.law_year)})</span> : null}{t.kind === 'stub' && <span className="text-amber-200/70"> · حل‌نشده</span>}</span>
              <span className="tnum shrink-0 text-[11px] text-white/40">{fa(t.articles)}</span>
            </button>
          ))}
        </Card>
        <div>
          {laws.error ? <LoadError error={laws.error} /> : !laws.data ? <Skeleton /> : (
            <>
              <div className="mb-3 text-[12px] text-white/40">{title || 'همهٔ قوانین'} · {fa(articles.length)} ماده{articles.length > PAGE ? ` · نمایش ${fa(PAGE)} مادهٔ اول` : ''}</div>
              <div className="space-y-2.5">{articles.slice(0, PAGE).map((a) => <ArticleCard key={a.id} a={a} onOpen={() => openInner(a.id, `مادهٔ ${fa(a.article_no ?? '')}`)} />)}</div>
              {!articles.length && !stubs.length && <Empty title="مادهٔ قانونی ثبت نشده است" />}
              {stubs.length > 0 && (
                <div className="mt-6">
                  <div className="mb-2 text-sm font-medium">ارجاع‌های حل‌نشده</div>
                  <p className="mb-3 text-[11.5px] text-white/40">پرونده‌ها به این مواد استناد کرده‌اند اما متن آن‌ها در پایگاه قوانین نیست — آن‌ها را از «افزودن ماده» کامل کنید.</p>
                  <div className="space-y-2">{stubs.map((a) => <ArticleCard key={a.id} a={a} onOpen={() => openInner(a.id, `مادهٔ ${fa(a.article_no ?? '')}`)} />)}</div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}

function ArticleCard({ a, onOpen }: { a: LawArticle; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className={cn('surface block w-full rounded-3xl p-4 text-start transition hover:bg-white/[.04]', a.kind === 'stub' && 'border-dashed border-amber-300/25')}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 text-[13px] font-medium text-white/90"><Scale className="h-4 w-4 text-amber-200/70" /> {a.article_no ? `مادهٔ ${fa(a.article_no)}` : a.kind_fa} — {a.law_title}</div>
        <Pill tone={a.kind === 'stub' ? 'warn' : 'neutral'}>{a.kind_fa}</Pill>
      </div>
      {a.title && <div className="mt-1 text-[12.5px] text-white/70">{a.title}</div>}
      {a.text && <p className="mt-1.5 line-clamp-2 text-[12px] leading-6 text-white/45">{a.text}</p>}
    </button>
  )
}

function Article({ id }: { id: string }) {
  const law = useQuery({ queryKey: ['law', id], queryFn: () => api.law(id) })
  const open = useShell((s) => s.open)
  usePublishContext('laws', { entityKind: 'law', entityLabel: law.data ? `مادهٔ ${fa(law.data.article_no ?? '')} ${law.data.law_title}`.slice(0, 40) : undefined, view: 'متن ماده' })
  if (law.error) return <LoadError error={law.error} retry={() => void law.refetch()} />
  if (!law.data) return <Skeleton />
  const a = law.data
  return (
    <>
      <PageHeader eyebrow={`${a.kind_fa} · ${a.law_title}${a.law_year ? ` (${fa(a.law_year)})` : ''}`} title={a.article_no ? `مادهٔ ${fa(a.article_no)}${a.title ? ` — ${a.title}` : ''}` : a.title ?? a.law_title} right={<Pill tone={a.kind === 'stub' ? 'warn' : 'neutral'}>{a.kind_fa}</Pill>} />
      <div className="mt-6 grid gap-5 lg:grid-cols-[1fr_380px]">
        <Card className="p-7">
          <p className="whitespace-pre-line text-[15px] leading-9 text-white/85">{a.text || 'متن این ماده در پایگاه قوانین ثبت نشده است.'}</p>
          {a.kind !== 'stub' && <div className="mt-4 text-[10.5px] text-white/30">متن خلاصه‌شده برای نمایش است — پیش از استفادهٔ واقعی با متن رسمی تطبیق دهید.</div>}
          {a.keywords?.length > 0 && <div className="mt-5"><Chips tone="amber" items={a.keywords} /></div>}
        </Card>
        <Card className="self-start">
          <CardHeader title="پرونده‌های استنادکننده" subtitle={`${fa(a.cited_by?.length ?? 0)} پرونده`} />
          <div className="space-y-1.5 px-5 pb-5">
            {(a.cited_by ?? []).map((c) => {
              const cn_ = (c as unknown as { case_number?: string }).case_number
              return (
                <button key={c.id} onClick={() => open('cases', { record: cn_ ?? c.id, label: fa(cn_ ?? '') })} className="flex w-full items-start gap-2 rounded-xl border border-white/[.05] px-3 py-2 text-start text-[12px] leading-6 text-white/75 hover:bg-white/[.03]">
                  <FolderOpen className="mt-1 h-3.5 w-3.5 shrink-0 text-cyan-200/60" /> {fa(c.label)}
                </button>
              )
            })}
            {!a.cited_by?.length && <div className="text-xs text-white/40">هیچ پرونده‌ای به این ماده استناد نکرده است.</div>}
          </div>
        </Card>
      </div>
    </>
  )
}

function LawSearch() {
  const [q, setQ] = useState('')
  const [submitted, setSubmitted] = useState('')
  const openInner = useShell((s) => s.openInner)
  const hits = useQuery({ queryKey: ['law-search', submitted], queryFn: () => api.laws({ q: submitted }), enabled: !!submitted })
  usePublishContext('laws', { filters: submitted ? { جستجو: submitted } : undefined })
  return (
    <>
      <PageHeader eyebrow="۱۵ · قوانین و مستندات" title="جستجو در قوانین" summary="جستجوی متنی در مواد — «ماده ۳۰ قانون بیمه» مستقیم به همان ماده می‌رسد." />
      <form className="mt-6 flex gap-2" onSubmit={(e) => { e.preventDefault(); setSubmitted(q.trim()) }}>
        <div className="glass flex flex-1 items-center gap-2 rounded-2xl px-3"><Search className="h-4 w-4 text-white/35" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="مثلاً: جانشینی بیمه‌گر، مرور زمان، ماده ۱۶" className="h-11 flex-1 bg-transparent text-[13px] outline-none" /></div>
        <Button type="submit" variant="primary" size="lg">جستجو</Button>
      </form>
      <div className="mt-5 space-y-2.5">
        {hits.isFetching && <div className="flex items-center gap-2 text-xs text-white/40"><Loader2 className="h-3.5 w-3.5 animate-spin" /> در حال جستجو…</div>}
        {hits.data && <div className="text-[12px] text-white/40">{fa(hits.data.items.length)} ماده برای «{submitted}»</div>}
        {hits.data?.items.map((a) => <ArticleCard key={a.id} a={a} onOpen={() => openInner(a.id, `مادهٔ ${fa(a.article_no ?? '')}`)} />)}
        {hits.error && <LoadError error={hits.error} />}
      </div>
    </>
  )
}

function AddLaw() {
  const { data: state } = useArchive()
  const refresh = useRefreshArchive()
  const openInner = useShell((s) => s.openInner)
  const [f, setF] = useState({ law_title: '', article_no: '', law_year: '', kind: 'law', title: '', text: '', keywords: '' })
  const [preview, setPreview] = useState(false)
  const save = useMutation({
    mutationFn: () => api.addLaw({ ...f, keywords: f.keywords.split(/[،,]/).map((k) => k.trim()).filter(Boolean), law_year: f.law_year || undefined, article_no: f.article_no || undefined, title: f.title || undefined }),
    onSuccess: (a) => { useAssistant.getState().toast({ tone: 'success', title: 'ماده ثبت شد', detail: `${a.law_title} — مادهٔ ${fa(a.article_no ?? '')}` }); useAssistant.getState().log({ kind: 'saved', text: `مادهٔ ${a.article_no} ${a.law_title} به پایگاه قوانین افزوده شد`, refs: [a.id] }); void refresh(); openInner(a.id, `مادهٔ ${fa(a.article_no ?? '')}`) },
  })
  const field = 'mt-1 h-10 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-[13px] outline-none focus:border-indigo-300/40'
  return (
    <>
      <PageHeader eyebrow="۱۵ · قوانین و مستندات" title="افزودن مادهٔ جدید" summary="ماده‌ای که با همان عنوان قانون و شمارهٔ ماده وجود داشته باشد به‌روز می‌شود؛ ارجاع‌های حل‌نشده به آن وصل می‌شوند." />
      <Card className="mt-6 max-w-3xl p-6">
        <div className="grid gap-3 sm:grid-cols-[1fr_120px_120px]">
          <label className="text-[11.5px] text-white/45">عنوان قانون / آیین‌نامه<input list="law-titles" className={field} value={f.law_title} onChange={(e) => setF({ ...f, law_title: e.target.value })} /><datalist id="law-titles">{state?.law_titles.map((t) => <option key={t.law_title} value={t.law_title} />)}</datalist></label>
          <label className="text-[11.5px] text-white/45">شمارهٔ ماده<input className={field} value={f.article_no} onChange={(e) => setF({ ...f, article_no: e.target.value })} /></label>
          <label className="text-[11.5px] text-white/45">سال تصویب<input className={field} value={f.law_year} onChange={(e) => setF({ ...f, law_year: e.target.value })} /></label>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[160px_1fr]">
          <label className="text-[11.5px] text-white/45">نوع<select className={field} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="law">قانون</option><option value="regulation">آیین‌نامه</option><option value="precedent">رأی وحدت رویه</option></select></label>
          <label className="text-[11.5px] text-white/45">عنوان ماده (اختیاری)<input className={field} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></label>
        </div>
        <label className="mt-3 block text-[11.5px] text-white/45">متن ماده<textarea rows={6} className={cn(field, 'h-auto py-2.5 leading-7')} value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></label>
        <label className="mt-3 block text-[11.5px] text-white/45">کلیدواژه‌ها (با ویرگول جدا کنید)<input className={field} value={f.keywords} onChange={(e) => setF({ ...f, keywords: e.target.value })} /></label>
        {preview && <div className="suggested mt-4 rounded-2xl p-3 text-[12.5px] leading-7 text-violet-50/90">ثبت می‌شود: <b>{f.kind === 'law' ? 'مادهٔ' : 'بند'} {fa(f.article_no)} {f.law_title}</b>{f.title ? ` — ${f.title}` : ''}. {state?.law_titles.some((t) => t.law_title === f.law_title) ? 'این قانون در پایگاه هست؛ ماده به آن افزوده یا به‌روز می‌شود.' : 'قانون تازه‌ای در پایگاه ساخته می‌شود.'}</div>}
        {save.error && <div className="mt-2 text-[12px] text-rose-200/80">{describeError(save.error)}</div>}
        <div className="mt-4 flex gap-2">
          {!preview ? <Button variant="primary" disabled={!f.law_title.trim() || !f.text.trim()} onClick={() => setPreview(true)}>پیش‌نمایش</Button> : <>
            <Button variant="ghost" onClick={() => setPreview(false)}>ویرایش</Button>
            <Button variant="approve" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} تأیید و ثبت</Button>
          </>}
        </div>
      </Card>
    </>
  )
}
