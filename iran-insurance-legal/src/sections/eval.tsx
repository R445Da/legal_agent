import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2, Play, SlidersHorizontal } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { fa, pct } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePublishContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import type { WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Pill } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'

type EvalResult = { top_k: number; n: number; metrics: Record<string, number>; cases: { q: string; kind?: string; rank: number | null; hit: boolean; retrieved: { source: string; similarity: number }[] }[] }

/**
 * ۱۳ ارزیابی بازیابی — score the retriever against eval/*.jsonl. Note the
 * baseline, change one thing, re-run, compare; the sweep does it for the
 * reranker, the setting with the largest effect on quality and latency.
 */
export function EvalView(_: { ws: WorkspaceTab }) {
  const files = useQuery({ queryKey: ['eval-files'], queryFn: api.evalFiles })
  const [path, setPath] = useState('eval/farsi.jsonl')
  const [topK, setTopK] = useState(5)
  const retrieval = useSettings((s) => s.retrieval)
  usePublishContext('eval', { filters: { مجموعه: path.replace('eval/', '') } })
  const once = useMutation({ mutationFn: () => api.evaluate({ path, top_k: topK }) as Promise<EvalResult> })
  const sweep = useMutation({ mutationFn: async () => { const off = await api.evaluate({ path, top_k: topK, rerank: false }) as EvalResult; const on = await api.evaluate({ path, top_k: topK, rerank: true }) as EvalResult; return { off, on } } })
  return (
    <>
      <PageHeader eyebrow="۱۳ · ارزیابی بازیابی" title="ارزیابی بازیابی" summary="hit@k، MRR و پوشش پرسش‌های چندسندی — با تنظیمات فعلی «بازیابی». تغییری بدهید، دوباره اجرا و مقایسه کنید." />
      <Card className="mt-6 flex flex-wrap items-end gap-3 p-5">
        <label className="text-[11.5px] text-white/45">مجموعهٔ ارزیابی<select className="mt-1 block h-10 rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none" value={path} onChange={(e) => setPath(e.target.value)}>{(files.data?.files ?? [path]).map((f) => <option key={f} value={f}>{f}</option>)}</select></label>
        <label className="text-[11.5px] text-white/45">top-k <input type="number" min={1} max={20} value={topK} onChange={(e) => setTopK(Number(e.target.value) || 5)} className="mt-1 block h-10 w-20 rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none" /></label>
        <div className="text-[11px] text-white/35">ترکیبی: {retrieval.hybrid ? 'روشن' : 'خاموش'} · بازرتبه‌بندی: {retrieval.rerank ? 'روشن' : 'خاموش'} · نامزدها: {fa(retrieval.candidates)}</div>
        <div className="ms-auto flex gap-2">
          <Button variant="primary" disabled={once.isPending} onClick={() => once.mutate()}>{once.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 -scale-x-100" />} اجرا</Button>
          <Button disabled={sweep.isPending} onClick={() => sweep.mutate()}>{sweep.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <SlidersHorizontal className="h-4 w-4" />} مقایسهٔ بازرتبه‌بندی</Button>
        </div>
      </Card>
      {(once.error || sweep.error) && <div className="mt-3 text-[12px] text-rose-200/80">{describeError(once.error ?? sweep.error)}</div>}
      {sweep.data && (
        <Card className="mt-5">
          <CardHeader title="مقایسهٔ بازرتبه‌بندی" />
          <div className="overflow-x-auto px-5 pb-5">
            <table className="w-full text-[12.5px]"><thead><tr className="text-white/35"><th className="py-2 text-start font-normal">معیار</th><th className="py-2 text-end font-normal">بدون بازرتبه‌بندی</th><th className="py-2 text-end font-normal">با بازرتبه‌بندی</th></tr></thead>
              <tbody>{Object.keys(sweep.data.off.metrics).map((k) => { const a = sweep.data!.off.metrics[k]; const b = sweep.data!.on.metrics[k]; return <tr key={k} className="border-t border-white/[.05]"><td className="py-2 text-white/70 ltr text-start">{k}</td><td className="tnum py-2 text-end">{pct(a)}</td><td className={cn('tnum py-2 text-end', b > a ? 'text-emerald-200' : b < a ? 'text-rose-200' : '')}>{pct(b)}</td></tr> })}</tbody></table>
          </div>
        </Card>
      )}
      {once.data && <Result r={once.data} />}
    </>
  )
}

function Result({ r }: { r: EvalResult }) {
  return (
    <>
      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        {Object.entries(r.metrics).map(([k, v]) => <Card key={k} className="p-4"><div className="ltr text-start text-xs text-white/40">{k}</div><div className="tnum mt-2 text-xl font-semibold">{pct(v)}</div></Card>)}
      </div>
      <Card className="mt-5">
        <CardHeader title="پرسش‌ها" subtitle={`${fa(r.n)} پرسش · top-${fa(r.top_k)}`} />
        <div className="divide-y divide-white/[.05]">
          {r.cases.map((c, i) => (
            <div key={i} className="px-5 py-3">
              <div className="flex items-start justify-between gap-3"><span className="text-[12.5px] leading-6 text-white/80">{c.q}</span><Pill tone={c.hit ? 'good' : 'bad'}>{c.hit ? `رتبهٔ ${fa(c.rank ?? 0)}` : 'یافت نشد'}</Pill></div>
              <div className="ltr mt-1 truncate text-start font-mono text-[10.5px] text-white/30">{c.retrieved.slice(0, 5).map((x) => x.source).join('  ·  ')}</div>
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}
