import { useMutation } from '@tanstack/react-query'
import { FlaskConical, Loader2, Search, Send } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive } from '@/api/queries'
import type { AnswerResult, RetrieveResult } from '@/api/types'
import { fa, pct } from '@/lib/format'
import { usePublishContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { AnswerCard } from '@/components/assistant/AnswerCard'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Pill } from '@/components/ui/misc'
import { Latency } from '@/components/shared/Latency'
import { PageHeader } from '@/components/shared/PageHeader'

/**
 * ۰۶ جستجو و پرسش — a cited answer, raw retrieval, and the retrieval lab
 * (the pipeline with and without the reranker, side by side).
 */
export function SearchView({ ws }: { ws: WorkspaceTab }) {
  const [collection, setCollection] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  usePublishContext('search', { filters: Object.fromEntries([...(collection ? [['مجموعه', collection]] : []), ...Object.entries(filters).filter(([, v]) => v)]) })
  const scope = { collection: collection || null, filters: Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) }
  return (
    <>
      <PageHeader eyebrow="۰۶ · جستجو و پرسش" title={{ ask: 'پرسش با پاسخ مستند', search: 'جستجوی متن', lab: 'آزمایشگاه بازیابی' }[ws.tab] ?? 'جستجو و پرسش'} summary="بازیابی ترکیبی (برداری + متنی، RRF) با بازرتبه‌بندی اختیاری — دکمه‌های آن در «تنظیمات › بازیابی»." />
      <Scope collection={collection} setCollection={setCollection} filters={filters} setFilters={setFilters} />
      {ws.tab === 'ask' && <Ask initial={ws.query ?? ''} scope={scope} />}
      {ws.tab === 'search' && <Retrieve scope={scope} />}
      {ws.tab === 'lab' && <Lab scope={scope} />}
    </>
  )
}

const FACET_FA: Record<string, string> = { year: 'سال', group: 'گروه', doc_kind: 'نوع سند', branch: 'شعبه', status: 'وضعیت' }
type ScopeT = { collection: string | null; filters: Record<string, string> }

function Scope({ collection, setCollection, filters, setFilters }: { collection: string; setCollection: (v: string) => void; filters: Record<string, string>; setFilters: (f: Record<string, string>) => void }) {
  const { data } = useArchive()
  const select = 'h-9 rounded-xl border border-white/10 bg-white/[.04] px-2 text-xs text-white/70 outline-none'
  return (
    <details className="mt-5 rounded-2xl border border-white/[.06] bg-white/[.02] px-4 py-2 text-xs text-white/55">
      <summary className="cursor-pointer py-1">دامنه و صافی‌ها {collection || Object.values(filters).some(Boolean) ? '· فعال' : ''}</summary>
      <div className="flex flex-wrap gap-2 py-2">
        <select className={select} value={collection} onChange={(e) => setCollection(e.target.value)} aria-label="مجموعه"><option value="">همهٔ مجموعه‌ها</option>{data?.collections.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select>
        {data && Object.entries(data.facets).filter(([, v]) => v.length).map(([k, values]) => (
          <select key={k} className={select} value={filters[k] ?? ''} onChange={(e) => setFilters({ ...filters, [k]: e.target.value })} aria-label={FACET_FA[k] ?? k}><option value="">{FACET_FA[k] ?? k}: همه</option>{values.map((v) => <option key={v.value} value={v.value}>{fa(v.value)}</option>)}</select>
        ))}
      </div>
    </details>
  )
}

function Ask({ initial, scope }: { initial: string; scope: ScopeT }) {
  const [q, setQ] = useState(initial)
  const ask = useMutation({ mutationFn: () => api.ask(q, scope) })
  const result = ask.data ? ({ ...ask.data, intent: 'query' } as AnswerResult) : null
  return (
    <Card className="mt-4 p-5">
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate() }}>
        <textarea value={q} onChange={(e) => setQ(e.target.value)} rows={3} placeholder="در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟" className="w-full resize-y rounded-2xl border border-white/10 bg-white/[.03] p-4 text-[14px] leading-7 outline-none focus:border-indigo-300/40" />
        <div className="mt-3 flex justify-end"><Button type="submit" variant="primary" disabled={!q.trim() || ask.isPending}>{ask.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4 -scale-x-100" />} پرسش با پاسخ مستند</Button></div>
      </form>
      {ask.error && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(ask.error)}</div>}
      {result && (
        <div className="mt-5 space-y-4">
          <Latency trace={result.retrieval} generate={result.latency_ms} />
          <div className="whitespace-pre-line text-[14px] leading-8 text-white/85">{result.answer}</div>
          <AnswerCard result={result} />
          <div className="text-[11px] text-white/30">مدل: <span className="ltr">{result.model}</span></div>
        </div>
      )}
    </Card>
  )
}

function Hits({ data }: { data: RetrieveResult }) {
  const open = useShell((s) => s.open)
  return (
    <div className="space-y-2">
      {data.hits.map((h) => (
        <div key={h.chunk_id} className="rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
          <div className="flex items-center justify-between gap-2 text-[12px]">
            <button onClick={() => open('documents', { record: h.document_id, label: h.title.slice(0, 24) })} className="min-w-0 truncate text-white/80 hover:text-white"><span className="tnum text-indigo-200">[{fa(h.n)}]</span> {fa(h.title)}</button>
            <span className="tnum shrink-0 text-white/40">{pct(h.similarity)}</span>
          </div>
          <p className="mt-1.5 line-clamp-3 text-[12px] leading-6 text-white/50">{h.text}</p>
        </div>
      ))}
    </div>
  )
}

function Retrieve({ scope }: { scope: ScopeT }) {
  const [q, setQ] = useState('')
  const run = useMutation({ mutationFn: () => api.retrieve(q, scope) })
  const open = useShell((s) => s.open)
  return (
    <Card className="mt-4 p-5">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) run.mutate() }}>
        <div className="flex flex-1 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.03] px-3"><Search className="h-4 w-4 text-white/35" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="چک برگشتی بانک ملت" className="h-11 flex-1 bg-transparent text-[13px] outline-none" /></div>
        <Button type="submit" variant="primary" size="lg" disabled={!q.trim() || run.isPending}>{run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'اجرا'}</Button>
      </form>
      <p className="mt-2 text-[11.5px] text-white/35">فقط بازیابی — بدون مدل زبانی. آنچه نمایه دقیقاً برمی‌گرداند.</p>
      {run.error && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(run.error)}</div>}
      {run.data && (
        <div className="mt-5 space-y-4">
          <Latency trace={run.data.trace} />
          {run.data.entries.length > 0 && (
            <div>
              <div className="mb-2 text-[12px] text-white/45">مدخل‌های یافت‌شده ({fa(run.data.entries.length)}) — تطبیق بر اساس واژه‌های کمیاب</div>
              <div className="space-y-1.5">{run.data.entries.map((e) => <button key={e.id} onClick={() => open('editor', { record: e.id, label: 'مدخل' })} className="block w-full rounded-xl border border-violet-300/10 bg-violet-300/[.04] px-3 py-2 text-start text-[12.5px] text-white/80 hover:bg-violet-300/[.07]">{fa(e.title)}<div className="line-clamp-1 text-[11px] text-white/40">{fa(e.summary)}</div></button>)}</div>
            </div>
          )}
          <Hits data={run.data} />
        </div>
      )}
    </Card>
  )
}

function Lab({ scope }: { scope: ScopeT }) {
  const [q, setQ] = useState('')
  const rerankModel = useSettings((s) => s.retrieval.rerank_model)
  const run = useMutation({ mutationFn: async () => { const [off, on] = await Promise.all([api.retrieve(q, { ...scope, rerank: false }), api.retrieve(q, { ...scope, rerank: true })]); return { off, on } } })
  return (
    <Card className="mt-4 p-5">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) run.mutate() }}>
        <div className="flex flex-1 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.03] px-3"><FlaskConical className="h-4 w-4 text-white/35" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="یک پرسش برای مقایسه" className="h-11 flex-1 bg-transparent text-[13px] outline-none" /></div>
        <Button type="submit" variant="primary" size="lg" disabled={!q.trim() || run.isPending}>{run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'مقایسه'}</Button>
      </form>
      <p className="mt-2 text-[11.5px] text-white/35">همان پرسش با و بدون بازرتبه‌بند متقاطع{rerankModel ? ` (${rerankModel})` : ''} — بزرگ‌ترین اهرم دقت و بیشترین هزینهٔ زمانی.</p>
      {run.error && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(run.error)}</div>}
      {run.data && (
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          {([['بدون بازرتبه‌بندی', run.data.off], ['با بازرتبه‌بندی', run.data.on]] as const).map(([title, d]) => (
            <Card key={title}>
              <CardHeader title={title} right={<Pill>{fa(d.hits.length)} نتیجه</Pill>} />
              <div className="space-y-3 px-5 pb-5"><Latency trace={d.trace} /><Hits data={d} /></div>
            </Card>
          ))}
        </div>
      )}
    </Card>
  )
}
