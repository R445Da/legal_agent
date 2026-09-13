import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Server } from 'lucide-react'
import { useEffect, useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useHealth, useModels, useOptions, useRefreshArchive } from '@/api/queries'
import type { Knob } from '@/api/types'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { defaultBase, useConnection } from '@/state/connection'
import { usePublishContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import type { WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Pill } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'

/**
 * تنظیمات — the Streamlit left panel: the active model (with only the knobs it
 * accepts), the retrieval dials that govern latency, speech-to-text, and the
 * connection to the API.
 */
export function SettingsView({ ws }: { ws: WorkspaceTab }) {
  usePublishContext('settings', {})
  return (
    <>
      <PageHeader eyebrow="تنظیمات" title={{ model: 'مدل', retrieval: 'بازیابی', speech: 'گفتار', connection: 'اتصال' }[ws.tab] ?? 'تنظیمات'} summary="این تنظیمات در همین مرورگر ذخیره می‌شوند و با هر درخواست به سرور فرستاده می‌شوند." />
      <div className="mt-6 max-w-3xl">
        {ws.tab === 'model' && <ModelPanel />}
        {ws.tab === 'retrieval' && <RetrievalPanel />}
        {ws.tab === 'speech' && <SpeechPanel />}
        {ws.tab === 'connection' && <ConnectionPanel />}
      </div>
    </>
  )
}

function Row({ title, help, children }: { title: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 border-t border-white/[.05] px-5 py-4 first:border-t-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0"><div className="text-[13px] text-white/85">{title}</div>{help && <div className="mt-0.5 text-[11.5px] leading-5 text-white/40">{help}</div>}</div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} className={cn('relative h-6 w-11 rounded-full border transition', checked ? 'border-emerald-300/30 bg-emerald-300/30' : 'border-white/10 bg-white/[.06]')}>
      <span className={cn('absolute top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-all', checked ? 'start-[22px]' : 'start-0.5')} />
    </button>
  )
}

function ModelPanel() {
  const models = useModels()
  const qc = useQueryClient()
  const { modelId, knobs, set, setKnob } = useSettings()
  const list = models.data?.models ?? []
  const current = list.find((m) => m.id === (modelId ?? models.data?.current)) ?? list.find((m) => m.id === models.data?.current)
  // Land on a model that works: if the stored pick is unavailable but another is, switch and say so.
  const [switched, setSwitched] = useState<string | null>(null)
  useEffect(() => {
    if (!models.data) return
    const picked = list.find((m) => m.id === modelId)
    if (modelId && (!picked || !picked.available)) {
      const fallback = list.find((m) => m.id === models.data!.current && m.available) ?? list.find((m) => m.available)
      if (fallback && fallback.id !== modelId) { setSwitched(`«${picked?.label ?? modelId}» در دسترس نیست — به «${fallback.label}» تغییر داده شد.`); set({ modelId: fallback.id }) }
    }
  }, [models.data]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="مدل فعال" subtitle="همهٔ مدل‌های محلی (Ollama) و ابری که سرور می‌شناسد — بدون نیاز به راه‌اندازی دوباره" right={<Button size="sm" variant="ghost" onClick={() => void qc.invalidateQueries({ queryKey: ['models'] })}><RefreshCw className="h-3.5 w-3.5" /> بازخوانی</Button>} />
        <div className="px-5 pb-5">
          {models.isLoading && <div className="flex items-center gap-2 text-xs text-white/40"><Loader2 className="h-3.5 w-3.5 animate-spin" /> در حال شناسایی مدل‌ها…</div>}
          {models.error && <div className="text-[12px] text-rose-200/80">{describeError(models.error)}</div>}
          <select className="h-11 w-full rounded-2xl border border-white/10 bg-white/[.04] px-3 text-[13px] outline-none" value={current?.id ?? ''} onChange={(e) => { set({ modelId: e.target.value, knobs: {} }); setSwitched(null) }}>
            {list.map((m) => <option key={m.id} value={m.id}>{m.available ? '' : '⚠ '}{m.label}</option>)}
          </select>
          {switched && <div className="mt-2 flex items-center gap-2 text-[12px] text-amber-200/85"><AlertTriangle className="h-3.5 w-3.5" /> {switched}</div>}
          {current && !current.available && <div className="mt-2 text-[12px] text-rose-200/80">{current.reason || 'این مدل در دسترس نیست'} — پیام‌ها ارسال نخواهند شد.</div>}
          {current?.reasoning && <div className="mt-2 text-[11.5px] text-white/40">مدل استدلالی — توکن‌های «فکر کردن» هم از سقف خروجی کم می‌شوند.</div>}
        </div>
      </Card>
      {current && current.knobs.length > 0 && (
        <Card>
          <CardHeader title="کلیدهای تنظیم مدل" subtitle="فقط کنترل‌هایی که همین مدل می‌پذیرد" />
          {current.knobs.map((k) => <KnobRow key={k.key} knob={k} value={knobs[k.key] ?? k.default} onChange={(v) => setKnob(k.key, v)} />)}
        </Card>
      )}
    </div>
  )
}

function KnobRow({ knob, value, onChange }: { knob: Knob; value: string | number | boolean; onChange: (v: string | number | boolean) => void }) {
  return (
    <Row title={knob.label} help={knob.help}>
      {knob.kind === 'toggle' ? <Toggle label={knob.label} checked={Boolean(value)} onChange={onChange} />
        : knob.kind === 'select' ? <div className="flex rounded-xl border border-white/10 bg-white/[.03] p-0.5 text-xs">{knob.options.map((o) => <button key={o} onClick={() => onChange(o)} className={cn('rounded-lg px-3 py-1.5', value === o ? 'bg-white/10 text-white' : 'text-white/45')}>{o}</button>)}</div>
        : <div className="flex items-center gap-3"><input type="range" min={knob.min} max={knob.max} step={knob.step} value={Number(value)} onChange={(e) => onChange(Number(e.target.value))} className="w-44 accent-indigo-300" /><span className="tnum w-14 text-end text-xs text-white/65">{fa(Number(value))}</span></div>}
    </Row>
  )
}

function RetrievalPanel() {
  const { topK, retrieval, set, setRetrieval } = useSettings()
  const { data: options } = useOptions()
  return (
    <Card>
      <CardHeader title="بازیابی" subtitle="مستقل از مدل — زمان پردازندهٔ سامانه اینجا صرف می‌شود." />
      <Row title="تعداد قطعه‌های داده‌شده به مدل"><Slider min={1} max={12} value={topK} onChange={(v) => set({ topK: v })} /></Row>
      <Row title="جستجوی ترکیبی (برداری + متنی، RRF)" help="خاموش = فقط برداری. سمت متنی است که نام‌ها، شماره‌ها و ارجاع‌های قانونی را می‌گیرد."><Toggle label="ترکیبی" checked={retrieval.hybrid} onChange={(v) => setRetrieval({ hybrid: v })} /></Row>
      <Row title="نامزدهای مرحلهٔ اول (هر سمت)" help="عمق فراخوانی. ارزان است — یک پرسمان Postgres، نه یک مدل."><Slider min={5} max={60} step={5} value={retrieval.candidates} onChange={(v) => setRetrieval({ candidates: v })} /></Row>
      <Row title="بازرتبه‌بندی متقاطع" help="بزرگ‌ترین اهرم دقت و بیشترین هزینهٔ زمانی: یک گذر پردازنده به ازای هر نامزد."><Toggle label="بازرتبه‌بندی" checked={retrieval.rerank} onChange={(v) => setRetrieval({ rerank: v })} /></Row>
      {retrieval.rerank && <>
        <Row title="تعداد نامزدهای بازرتبه‌بندی‌شده" help="زمان با این عدد خطی است."><Slider min={3} max={30} value={retrieval.rerank_top} onChange={(v) => setRetrieval({ rerank_top: v })} /></Row>
        <Row title="مدل بازرتبه‌بندی" help="فقط مدل‌های چندزبانه فارسی را درست امتیاز می‌دهند."><select className="h-9 rounded-xl border border-white/10 bg-white/[.04] px-2 text-xs outline-none" value={retrieval.rerank_model ?? options?.rerank.default ?? ''} onChange={(e) => setRetrieval({ rerank_model: e.target.value })}>{options?.rerank.choices.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select></Row>
      </>}
      {options && <div className="border-t border-white/[.05] px-5 py-3 text-[11px] text-white/35">مدل تعبیه: <span className="ltr">{options.retrieval.embedding_model}</span></div>}
    </Card>
  )
}

function Slider({ min, max, step = 1, value, onChange }: { min: number; max: number; step?: number; value: number; onChange: (v: number) => void }) {
  return <div className="flex items-center gap-3"><input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-44 accent-indigo-300" /><span className="tnum w-8 text-end text-xs text-white/65">{fa(value)}</span></div>
}

function SpeechPanel() {
  const { data: options } = useOptions()
  const { sttChoice, speakReplies, set } = useSettings()
  return (
    <Card>
      <CardHeader title="گفتار" subtitle="میکروفون کنار نوشتار است؛ ضبط کردن یعنی فرستادن." />
      <Row title="مدل گفتار به متن" help={options?.stt.enabled ? 'مدل‌های Groq روی شبکه اجرا می‌شوند و بسیار سریع‌ترند؛ مدل‌های محلی نیازی به کلید ندارند.' : 'گفتار به متن روی سرور غیرفعال است (STT=0) — تشخیص گفتار مرورگر (fa-IR) به کار می‌رود.'}>
        {options?.stt.enabled ? <select className="h-9 rounded-xl border border-white/10 bg-white/[.04] px-2 text-xs outline-none" value={sttChoice ?? options.stt.default ?? ''} onChange={(e) => set({ sttChoice: e.target.value })}>{options.stt.choices.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</select> : <Pill>مرورگر</Pill>}
      </Row>
      <Row title="خواندن پاسخ‌ها با صدا" help="پاسخ کوتاه دستیار با صدای فارسی مرورگر خوانده می‌شود."><Toggle label="خواندن پاسخ" checked={speakReplies} onChange={(v) => set({ speakReplies: v })} /></Row>
    </Card>
  )
}

function ConnectionPanel() {
  const conn = useConnection()
  const health = useHealth()
  const refresh = useRefreshArchive()
  const qc = useQueryClient()
  const [base, setBase] = useState(conn.baseUrl)
  const [token, setToken] = useState(conn.token)
  const resync = useMutation({ mutationFn: api.resync, onSuccess: (r) => { useAssistant.getState().toast({ tone: 'success', title: 'آرشیو دوباره همگام شد', detail: `${fa(r.entries)} مدخل` }); void refresh() } })
  const h = health.data
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Server className="h-4 w-4 text-white/50" /> سرور API</span>} subtitle="app/main.py — همان موتوری که Streamlit مستقیم فراخوانی می‌کند" right={h ? <Pill tone="good" dot>متصل</Pill> : <Pill tone="bad" dot>قطع</Pill>} />
        <div className="grid gap-3 px-5 pb-5 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <label className="text-[11.5px] text-white/45">نشانی سرور<input dir="ltr" value={base} onChange={(e) => setBase(e.target.value)} placeholder={defaultBase() || 'همان مبدأ'} className="mt-1 h-10 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none" /></label>
          <label className="text-[11.5px] text-white/45">توکن API<input dir="ltr" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="API_TOKEN در ‎.env" className="mt-1 h-10 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none" /></label>
          <Button onClick={() => { conn.set({ baseUrl: base, token }); void qc.invalidateQueries() }}>ذخیره و آزمون</Button>
        </div>
        {health.error && <div className="px-5 pb-4 text-[12px] text-rose-200/80">{describeError(health.error)}</div>}
        {h && <div className="flex flex-wrap gap-2 px-5 pb-5 text-[11px]"><Pill>{h.llm_provider} · <span className="ltr">{h.llm_model}</span></Pill><Pill tone={h.llm_available ? 'good' : 'warn'}>مدل {h.llm_available ? 'در دسترس' : 'در دسترس نیست'}</Pill><Pill>{fa(h.indexed_documents ?? 0)} سند · {fa(h.indexed_chunks ?? 0)} قطعه</Pill><Pill tone={h.stt_available ? 'good' : 'neutral'}>گفتار {h.stt_available ? 'روشن' : 'خاموش'}</Pill>{h.auth_required && <Pill tone="info">نیازمند توکن</Pill>}</div>}
      </Card>
      <Card>
        <Row title="بازخوانی آرشیو" help="همهٔ داده‌های این رابط را از سرور دوباره بخوان."><Button onClick={() => void refresh()}><RefreshCw className="h-4 w-4" /> بازخوانی</Button></Row>
        <Row title="همگام‌سازی دوبارهٔ پرونده‌ها و گراف" help="پرونده‌ها، اشخاص، سازمان‌ها و یال‌های گراف را از روی همهٔ مدخل‌ها بازسازی می‌کند (POST /archive/resync).">
          <Button disabled={resync.isPending} onClick={() => resync.mutate()}>{resync.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} همگام‌سازی</Button>
        </Row>
      </Card>
    </div>
  )
}
