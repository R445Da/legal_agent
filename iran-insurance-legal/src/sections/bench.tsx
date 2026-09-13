import { useMutation } from '@tanstack/react-query'
import { Loader2, Play } from 'lucide-react'
import { useMemo, useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useModels } from '@/api/queries'
import { fa, ms } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePublishContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import type { WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'

type Cell = { model_id: string; model: string; answer?: string; error?: string; latency_ms?: number; input_tokens?: number; output_tokens?: number }
type BenchResult = { top_k: number; rows: { question: string; cells: Cell[] }[]; summary: Record<string, unknown>[] | Record<string, unknown> }

/**
 * ۱۴ مقایسهٔ مدل‌ها — the same questions through several models side by side.
 * Retrieval runs once per question and is reused, so the grid compares only
 * the answer-generation step.
 */
export function BenchView(_: { ws: WorkspaceTab }) {
  const models = useModels()
  const current = useSettings((s) => s.modelId)
  const [picked, setPicked] = useState<string[]>([])
  const [questions, setQuestions] = useState('در پرونده کالای معیوب دادگاه چه تصمیمی گرفت؟')
  const available = useMemo(() => (models.data?.models ?? []).filter((m) => m.available), [models.data])
  usePublishContext('bench', {})
  const chosen = picked.length ? picked : [current ?? models.data?.current].filter(Boolean) as string[]
  const run = useMutation({ mutationFn: () => api.bench(questions.split('\n').map((q) => q.trim()).filter(Boolean).slice(0, 20), chosen.slice(0, 8), 5) as Promise<BenchResult> })
  return (
    <>
      <PageHeader eyebrow="۱۴ · مقایسهٔ مدل‌ها" title="مقایسهٔ مدل‌ها" summary="بازیابی برای هر پرسش یک‌بار اجرا و میان همهٔ مدل‌ها بازاستفاده می‌شود؛ پس این جدول فقط تولید پاسخ را مقایسه می‌کند." />
      <Card className="mt-6 space-y-4 p-5">
        <div>
          <div className="mb-2 text-[11.5px] text-white/45">مدل‌ها (حداکثر ۸) — فقط مدل‌های در دسترس</div>
          <div className="flex flex-wrap gap-1.5">
            {available.map((m) => {
              const on = chosen.includes(m.id)
              return <button key={m.id} onClick={() => setPicked(on ? chosen.filter((x) => x !== m.id) : [...chosen, m.id].slice(0, 8))} className={cn('rounded-full border px-3 py-1 text-[11.5px]', on ? 'border-indigo-300/40 bg-indigo-300/15 text-indigo-50' : 'border-white/10 text-white/55 hover:text-white')}>{m.label}</button>
            })}
            {!available.length && <span className="text-xs text-white/40">{models.isLoading ? 'در حال شناسایی مدل‌ها…' : 'مدل در دسترسی نیست.'}</span>}
          </div>
        </div>
        <label className="block text-[11.5px] text-white/45">پرسش‌ها — هر خط یک پرسش<textarea rows={4} value={questions} onChange={(e) => setQuestions(e.target.value)} className="mt-1 w-full rounded-2xl border border-white/10 bg-white/[.03] p-3 text-[13px] leading-7 outline-none" /></label>
        <Button variant="primary" disabled={!chosen.length || !questions.trim() || run.isPending} onClick={() => run.mutate()}>{run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 -scale-x-100" />} اجرای مقایسه</Button>
        {run.error && <div className="text-[12px] text-rose-200/80">{describeError(run.error)}</div>}
      </Card>
      {run.data && run.data.rows.map((row) => (
        <Card key={row.question} className="mt-5">
          <CardHeader title={row.question} />
          <div className="grid gap-3 px-5 pb-5 md:grid-cols-2 xl:grid-cols-3">
            {row.cells.map((c) => (
              <div key={c.model_id} className="rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
                <div className="flex items-center justify-between gap-2 text-[11px]"><span className="ltr truncate text-white/70">{c.model}</span><span className="tnum text-white/40">{ms(c.latency_ms)}</span></div>
                {c.error ? <div className="mt-2 text-[12px] text-rose-200/80">{c.error}</div> : <p className="mt-2 max-h-72 overflow-y-auto whitespace-pre-line text-[12.5px] leading-7 text-white/75">{c.answer}</p>}
                {(c.input_tokens || c.output_tokens) ? <div className="tnum mt-2 text-[10.5px] text-white/30">{fa(c.input_tokens ?? 0)} ← {fa(c.output_tokens ?? 0)} توکن</div> : null}
              </div>
            ))}
          </div>
        </Card>
      ))}
    </>
  )
}
