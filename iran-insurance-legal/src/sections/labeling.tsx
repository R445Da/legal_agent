import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Search, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { ago, fa, pct } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePublishContext } from '@/state/context'
import type { WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill, Stat } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/**
 * ۱۰ برچسب‌گذاری و بازخورد — run a query, mark each retrieved chunk relevant or
 * not; the judgments accumulate into an eval set. Twenty to fifty real
 * judgments are worth more than any model swap.
 */
export function LabelingView({ ws }: { ws: WorkspaceTab }) {
  const summary = useQuery({ queryKey: ['labels-summary'], queryFn: api.labelsSummary })
  usePublishContext('labeling', {})
  return (
    <>
      <PageHeader eyebrow="۱۰ · برچسب‌گذاری و بازخورد" title={ws.tab === 'labels' ? 'برچسب‌های ثبت‌شده' : 'داوری نتایج'} summary="هر داوری شما یک برچسب «مرتبط / نامرتبط» است که ارزیابی بازیابی از آن ساخته می‌شود." />
      {summary.data && (
        <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label="پرسش‌های داوری‌شده" value={fa(summary.data.relevance_queries)} />
          <Stat label="آمادهٔ ارزیابی" value={fa(summary.data.eval_ready_queries)} hint="دست‌کم یک مورد مرتبط" tone="good" />
          <Stat label="اسناد برچسب‌خورده" value={fa(summary.data.documents_tagged)} />
          <Stat label="همهٔ برچسب‌ها" value={fa(Object.values(summary.data.by_kind).reduce((s, n) => s + n, 0))} />
        </div>
      )}
      {ws.tab === 'labels' ? <LabelList /> : <Judge />}
    </>
  )
}

function Judge() {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [query, setQuery] = useState('')
  const hits = useQuery({ queryKey: ['label-retrieve', query], queryFn: () => api.retrieve(query, { top_k: 8 }), enabled: !!query })
  const existing = useQuery({ queryKey: ['labels', 'relevance'], queryFn: () => api.labels({ kind: 'relevance', limit: 2000 }) })
  const mark = useMutation({
    mutationFn: (v: { chunk: string; value: '1' | '0' }) => api.addLabel({ kind: 'relevance', target_type: 'chunk', target_id: v.chunk, value: v.value, query }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['labels'] }); void qc.invalidateQueries({ queryKey: ['labels-summary'] }) },
  })
  const judged = (chunk: string) => existing.data?.find((l) => l.target_id === chunk && l.query === query)?.value
  return (
    <Card className="mt-5 p-5">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()) }}>
        <div className="flex flex-1 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.03] px-3"><Search className="h-4 w-4 text-white/35" /><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="پرسشی که وکلا واقعاً می‌پرسند…" className="h-11 flex-1 bg-transparent text-[13px] outline-none" /></div>
        <Button type="submit" variant="primary" size="lg">بازیابی</Button>
      </form>
      {hits.isFetching && <div className="mt-4 flex items-center gap-2 text-xs text-white/40"><Loader2 className="h-3.5 w-3.5 animate-spin" /> در حال بازیابی…</div>}
      {hits.error && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(hits.error)}</div>}
      <div className="mt-4 space-y-2.5">
        {hits.data?.hits.map((h) => {
          const v = judged(h.chunk_id)
          return (
            <div key={h.chunk_id} className={cn('rounded-2xl border p-3', v === '1' ? 'border-emerald-300/25 bg-emerald-300/[.04]' : v === '0' ? 'border-rose-300/20 bg-rose-400/[.03]' : 'border-white/[.06] bg-white/[.02]')}>
              <div className="flex items-center justify-between gap-2 text-[12px]"><span className="min-w-0 truncate text-white/80"><span className="tnum text-indigo-200">[{fa(h.n)}]</span> {fa(h.title)}</span><span className="tnum text-white/40">{pct(h.similarity)}</span></div>
              <p className="mt-1.5 line-clamp-4 text-[12px] leading-6 text-white/55">{h.text}</p>
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant={v === '1' ? 'approve' : 'secondary'} onClick={() => mark.mutate({ chunk: h.chunk_id, value: '1' })}><ThumbsUp className="h-3.5 w-3.5" /> مرتبط</Button>
                <Button size="sm" variant={v === '0' ? 'danger' : 'secondary'} onClick={() => mark.mutate({ chunk: h.chunk_id, value: '0' })}><ThumbsDown className="h-3.5 w-3.5" /> نامرتبط</Button>
              </div>
            </div>
          )
        })}
        {!query && <div className="text-xs text-white/35">یک پرسش بنویسید و نتایج را داوری کنید. داوری دوباره همان مورد، مقدار قبلی را جایگزین می‌کند.</div>}
      </div>
    </Card>
  )
}

function LabelList() {
  const qc = useQueryClient()
  const labels = useQuery({ queryKey: ['labels', 'all'], queryFn: () => api.labels({ limit: 300 }) })
  const remove = useMutation({ mutationFn: (id: string) => api.deleteLabel(id), onSuccess: () => { void qc.invalidateQueries({ queryKey: ['labels'] }); void qc.invalidateQueries({ queryKey: ['labels-summary'] }) } })
  if (labels.error) return <LoadError error={labels.error} />
  if (!labels.data) return <Skeleton />
  const KIND: Record<string, string> = { relevance: 'مرتبط بودن', tag: 'برچسب', review: 'بازبینی' }
  return (
    <Card className="mt-5">
      <CardHeader title="آخرین برچسب‌ها" subtitle={`${fa(labels.data.length)} مورد`} />
      <div className="divide-y divide-white/[.05]">
        {labels.data.map((l) => (
          <div key={l.id} className="flex items-center gap-3 px-5 py-2.5 text-[12.5px]">
            <Pill tone={l.kind === 'relevance' ? (l.value === '1' ? 'good' : 'bad') : l.kind === 'review' ? 'warn' : 'info'}>{KIND[l.kind]}{l.kind === 'relevance' ? (l.value === '1' ? ' · مرتبط' : ' · نامرتبط') : l.value ? ` · ${l.value}` : ''}</Pill>
            <span className="min-w-0 flex-1 truncate text-white/65">{l.query ?? l.note ?? `${l.target_type} ${l.target_id.slice(0, 8)}`}</span>
            <span className="text-[11px] text-white/30">{l.created_at ? ago(l.created_at) : ''}</span>
            <button onClick={() => remove.mutate(l.id)} aria-label="حذف" className="text-white/30 hover:text-rose-200"><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
        ))}
        {!labels.data.length && <Empty title="هنوز برچسبی ثبت نشده" />}
      </div>
    </Card>
  )
}
