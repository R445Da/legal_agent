import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, FileUp, Loader2, Play, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive, useRefreshArchive } from '@/api/queries'
import { ask, refreshArchive } from '@/assistant/runtime'
import { ago, fa } from '@/lib/format'
import { asText, cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import { isRunTab, RUN_PREFIX, useShell, type WorkspaceTab } from '@/state/shell'
import { RunCard } from '@/components/assistant/RunCard'
import { MessageControls } from '@/components/assistant/MessageControls'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill } from '@/components/ui/misc'
import { Chips } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/**
 * ۰۵ بایگانی سند جدید — a new session or document into the archive.
 * «استخراج ساختاریافته» runs the human-gated entry pipeline (the same one the
 * assistant uses); «بارگذاری فایل» indexes plain files; «اجراهای خط لوله»
 * lists every run, resumable from where it stopped.
 */
export function IngestView({ ws }: { ws: WorkspaceTab }) {
  if (ws.active && isRunTab(ws.active)) return <RunTab runId={ws.active.slice(RUN_PREFIX.length)} />
  if (ws.tab === 'files') return <Files />
  if (ws.tab === 'runs') return <Runs />
  return <Structured />
}

function Structured() {
  const [text, setText] = useState('')
  const [mode, setMode] = useState<'pipeline' | 'preview'>('pipeline')
  const busy = useAssistant((s) => s.busy)
  const openRun = useShell((s) => s.openRun)
  usePublishContext('ingest', { view: 'استخراج ساختاریافته' })
  const preview = useMutation({ mutationFn: () => api.extractPreview(text) })
  const startPipeline = async () => {
    const before = new Set(Object.keys(useAssistant.getState().runs))
    await ask(text, 'assistant', 'archive')
    const created = Object.keys(useAssistant.getState().runs).find((id) => !before.has(id))
    if (created) { openRun(created, 'ثبت مطلب', 'tab'); setText('') }
  }
  return (
    <>
      <PageHeader eyebrow="۰۵ · بایگانی سند جدید" title="استخراج ساختاریافته" summary="متن جلسه یا سند را بچسبانید. دستیار مدخل را استخراج می‌کند، مستندات قانونی، خط زمان و پرونده‌های مشابه را پیدا می‌کند و برای تأیید شما می‌ایستد. پیش از تأیید چیزی نوشته نمی‌شود." />
      <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_380px]">
        <Card className="p-5">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12} placeholder={'صورت‌جلسهٔ رسیدگی شعبهٔ ۳ دادگاه حقوقی تهران\nخواهان: شرکت سهامی بیمه ایران (با وکالت آقای رضا کریمی)\nخوانده: آقای علی مرادی\n…'} className="w-full resize-y rounded-2xl border border-white/10 bg-white/[.03] p-4 text-[13.5px] leading-8 outline-none focus:border-indigo-300/40" />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="flex rounded-xl border border-white/10 bg-white/[.03] p-0.5 text-xs">
              <button onClick={() => setMode('pipeline')} className={cn('rounded-lg px-3 py-1.5', mode === 'pipeline' ? 'bg-white/10 text-white' : 'text-white/50')}>خط لولهٔ کامل</button>
              <button onClick={() => setMode('preview')} className={cn('rounded-lg px-3 py-1.5', mode === 'preview' ? 'bg-white/10 text-white' : 'text-white/50')}>فقط پیش‌نمایش</button>
            </div>
            {mode === 'pipeline' ? <Button variant="primary" className="ms-auto" disabled={!text.trim() || busy} onClick={startPipeline}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 -scale-x-100" />} استخراج و آغاز ثبت</Button>
              : <Button variant="primary" className="ms-auto" disabled={!text.trim() || preview.isPending} onClick={() => preview.mutate()}>{preview.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} استخراج و پیش‌نمایش</Button>}
          </div>
          {mode === 'pipeline' && <MessageControls className="mt-3 justify-start" />}
        </Card>
        <Card className="self-start p-5 text-[12.5px] leading-7 text-white/55">
          <div className="mb-2 text-sm font-medium text-white/85">چه اتفاقی می‌افتد؟</div>
          <ol className="list-inside list-decimal space-y-1">
            <li>تشخیص نوع و استخراج ساختاریافته (طرفین، رویدادها، شماره پرونده، رشتهٔ بیمه…)</li>
            <li>اتصال استنادها به پایگاه قوانین</li>
            <li>خط زمان، پرونده‌های مشابه و برچسب‌ها</li>
            <li className="text-amber-100/80">توقف برای تأیید شما — حالت ثبت: «{({ review: 'تأیید یک‌باره', steps: 'گام‌به‌گام', auto: 'خودکار', conversation: 'گفتگویی' } as Record<string, string>)[useSettings.getState().runMode]}»</li>
            <li>ثبت: مدخل، سند، پرونده، اشخاص، استنادها و گراف</li>
          </ol>
        </Card>
      </div>
      {mode === 'preview' && (preview.error ? <div className="mt-4 text-[12px] text-rose-200/80">{describeError(preview.error)}</div> : preview.data && <Preview data={preview.data} text={text} onDone={() => setText('')} />)}
    </>
  )
}

/** The old two-step flow: preview the extraction, then commit it as-is. */
function Preview({ data, text, onDone }: { data: Awaited<ReturnType<typeof api.extractPreview>>; text: string; onDone: () => void }) {
  const [source, setSource] = useState(`web/${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}`)
  const commit = useMutation({
    mutationFn: () => api.commitDraft(data.draft, text, source),
    onSuccess: (r) => {
      useAssistant.getState().toast({ tone: 'success', title: 'در آرشیو ثبت شد', detail: r.title, undo: async () => { await api.deleteEntry(r.id, true); useAssistant.getState().toast({ tone: 'info', title: 'ثبت برگردانده شد' }); void refreshArchive() } })
      useAssistant.getState().log({ kind: 'committed', text: `مدخل «${r.title}» از پیش‌نمایش ثبت شد`, refs: [r.id] })
      void refreshArchive(); onDone()
    },
  })
  const d = data.draft as Record<string, unknown> & { entities?: Record<string, unknown> }
  return (
    <Card className="suggested mt-5 p-5">
      <div className="flex items-center gap-2 text-[11px] text-violet-200/80"><Sparkles className="h-3.5 w-3.5" /> پیش‌نویس دستیار — هنوز ثبت نشده</div>
      <div className="mt-2 text-[15px] font-semibold">{asText(d.title) || 'بدون عنوان'}</div>
      <p className="mt-1 text-[12.5px] leading-7 text-white/60">{asText(d.summary)}</p>
      <div className="mt-3 grid gap-x-6 gap-y-1 text-[12px] sm:grid-cols-2">
        {Object.entries(d.entities ?? {}).filter(([, v]) => asText(v)).map(([k, v]) => <div key={k}><span className="text-white/35">{k}: </span><span className="text-white/75">{fa(asText(v))}</span></div>)}
      </div>
      <div className="mt-3"><Chips tone="teal" items={((d.tags as string[]) ?? [])} /></div>
      {data.related?.length > 0 && <div className="mt-3 text-[11.5px] text-white/45">مرتبط: {data.related.map((r) => r.title).join('، ')}</div>}
      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="text-[11px] text-white/45">شناسهٔ منبع<input value={source} onChange={(e) => setSource(e.target.value)} className="ltr mt-1 block h-9 w-64 rounded-xl border border-white/10 bg-white/[.04] px-3 font-mono text-xs outline-none" /></label>
        <Button variant="approve" disabled={commit.isPending} onClick={() => commit.mutate()}>{commit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} تأیید و ثبت در آرشیو</Button>
      </div>
      {commit.error && <div className="mt-2 text-[12px] text-rose-200/80">{describeError(commit.error)}</div>}
    </Card>
  )
}

function Files() {
  const { data: state } = useArchive()
  const refresh = useRefreshArchive()
  const [files, setFiles] = useState<File[]>([])
  const [collection, setCollection] = useState('uploads')
  const [extract, setExtract] = useState(true)
  usePublishContext('ingest', { view: 'بارگذاری فایل' })
  const upload = useMutation({
    mutationFn: async () => api.ingest(await Promise.all(files.map(async (f) => ({ text: await f.text(), source: `upload/${f.name}`, title: f.name.replace(/\.(txt|md)$/, ''), metadata: { collection } }))), extract),
    onSuccess: (r) => { useAssistant.getState().toast({ tone: 'success', title: `${fa(r.results.length)} فایل بایگانی شد`, detail: extract ? 'استخراج ساختاریافته در پس‌زمینه اجرا می‌شود.' : undefined }); useAssistant.getState().log({ kind: 'saved', text: `${r.results.length} فایل در «${collection}» بایگانی شد`, refs: [] }); setFiles([]); void refresh() },
  })
  return (
    <>
      <PageHeader eyebrow="۰۵ · بایگانی سند جدید" title="بارگذاری فایل" summary="فایل‌های متنی (txt / md) نمایه می‌شوند؛ در صورت انتخاب، برای هر سند یک مدخل ساختاریافته در پس‌زمینه ساخته می‌شود." />
      <Card className="mt-6 max-w-3xl p-6">
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-3xl border border-dashed border-white/15 bg-white/[.02] px-6 py-10 text-center hover:bg-white/[.04]">
          <FileUp className="h-6 w-6 text-white/40" />
          <span className="mt-2 text-[13px] text-white/70">فایل‌ها را انتخاب کنید</span>
          <span className="text-[11px] text-white/35">txt یا md — چند فایل با هم</span>
          <input type="file" accept=".txt,.md,text/plain" multiple className="hidden" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </label>
        {files.length > 0 && (
          <div className="mt-4 space-y-3">
            <ul className="space-y-1 text-[12.5px] text-white/70">{files.map((f) => <li key={f.name} className="flex justify-between"><span className="ltr">{f.name}</span><span className="tnum text-white/35">{fa(Math.round(f.size / 1024))} کیلوبایت</span></li>)}</ul>
            <div className="flex flex-wrap items-center gap-3">
              <label className="text-[11.5px] text-white/45">مجموعهٔ مقصد <select value={collection} onChange={(e) => setCollection(e.target.value)} className="ms-1 h-9 rounded-xl border border-white/10 bg-white/[.04] px-2 text-xs outline-none">{[...(state?.collections.map((c) => c.name) ?? []), 'uploads'].filter((v, i, a) => a.indexOf(v) === i).map((c) => <option key={c}>{c}</option>)}</select></label>
              <label className="flex items-center gap-2 text-[12px] text-white/55"><input type="checkbox" className="accent-emerald-300" checked={extract} onChange={(e) => setExtract(e.target.checked)} /> استخراج ساختاریافته در پس‌زمینه</label>
            </div>
            <div className="suggested rounded-2xl p-3 text-[12px] text-violet-50/85">{fa(files.length)} سند در «{collection}» نمایه می‌شود{extract ? ' و برای هر کدام مدخلی استخراج می‌شود' : ''}. سندی با همان منبع قبلاً ثبت شده باشد، رد می‌شود.</div>
            <Button variant="approve" disabled={upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} تأیید و بایگانی فایل‌ها</Button>
            {upload.data && <ul className="text-[11.5px] text-white/50">{upload.data.results.map((r) => <li key={r.source}>{r.source}: {({ created: 'ثبت شد', replaced: 'جایگزین شد', skipped: 'تکراری — رد شد', empty: 'خالی' } as Record<string, string>)[r.status] ?? r.status} ({fa(r.chunks)} قطعه)</li>)}</ul>}
            {upload.error && <div className="text-[12px] text-rose-200/80">{describeError(upload.error)}</div>}
          </div>
        )}
      </Card>
    </>
  )
}

function Runs() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: () => api.runs(60), refetchInterval: 8000 })
  const openRun = useShell((s) => s.openRun)
  usePublishContext('ingest', { view: 'اجراهای خط لوله' })
  if (runs.error) return <LoadError error={runs.error} retry={() => void runs.refetch()} />
  if (!runs.data) return <Skeleton />
  const tone = (s: string) => (s === 'committed' ? 'good' : s === 'awaiting_input' ? 'warn' : s === 'failed' ? 'bad' : 'neutral') as 'good' | 'warn' | 'bad' | 'neutral'
  const label: Record<string, string> = { committed: 'ثبت شد', awaiting_input: 'در انتظار تأیید', failed: 'ناموفق', abandoned: 'متوقف', running: 'در حال اجرا' }
  return (
    <>
      <PageHeader eyebrow="۰۵ · بایگانی سند جدید" title="اجراهای خط لوله" summary="هر ثبت یک اجرای ماندگار است؛ بارگذاری دوباره یا خطای مدل چیزی را از بین نمی‌برد و از همان‌جا ادامه می‌یابد." right={<Pill>{fa(runs.data.runs.length)} اجرا</Pill>} />
      <Card className="mt-6 divide-y divide-white/[.05]">
        {runs.data.runs.map((r) => (
          <button key={r.id} onClick={() => { openRun(r.id, (asText((r.state?.draft as { title?: string } | undefined)?.title) || 'ثبت مطلب').slice(0, 22), 'tab') }} className="flex w-full items-center gap-4 px-5 py-3 text-start transition hover:bg-white/[.025]">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] text-white/85">{asText((r.state?.draft as { title?: string } | undefined)?.title) || (r.raw_text ?? '').split('\n')[0].slice(0, 90) || 'ثبت مطلب'}</div>
              <div className="text-[11px] text-white/35">{r.updated_at ? ago(r.updated_at) : '—'} · <span className="ltr">{r.source}</span></div>
            </div>
            <Pill tone={tone(r.status)} dot>{label[r.status] ?? r.status}</Pill>
          </button>
        ))}
        {!runs.data.runs.length && <Empty title="هنوز اجرایی ثبت نشده" detail="از «استخراج ساختاریافته» یا از دستیار یک مطلب جدید ثبت کنید." />}
      </Card>
    </>
  )
}

function RunTab({ runId }: { runId: string }) {
  usePublishContext('ingest', { entityKind: 'run', entityLabel: 'ثبت مطلب', view: 'بازبینی ثبت' })
  return (
    <>
      <PageHeader eyebrow="۰۵ · ثبت مطلب" title="بازبینی و تأیید ثبت" summary="پیش‌نویس دستیار تا وقتی تأیید نکنید در آرشیو نوشته نمی‌شود." />
      <div className="mt-6 max-w-4xl"><RunCard runId={runId} /></div>
      <Card className="mt-5 max-w-4xl"><CardHeader title="متن ورودی" /><RawText runId={runId} /></Card>
    </>
  )
}

function RawText({ runId }: { runId: string }) {
  const run = useAssistant((s) => s.runs[runId])
  return <div className="whitespace-pre-wrap px-5 pb-5 text-[13px] leading-8 text-white/60">{run?.raw_text ?? '…'}</div>
}
