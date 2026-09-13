import { AnimatePresence, motion } from 'framer-motion'
import { Ban, CheckCircle2, ChevronDown, CircleCheck, FolderOpen, Hand, Loader2, PenLine, Plus, RotateCcw, ShieldCheck, Sparkles, Trash2, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useOptions } from '@/api/queries'
import type { EntryRun, RunStep } from '@/api/types'
import { abandonRun, approveGate, retryRun, syncRun, undoCommit } from '@/assistant/runtime'
import { fa } from '@/lib/format'
import { asText, cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { useShell } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Pill } from '@/components/ui/misc'
import { RunStepper } from './RunStepper'

/**
 * A filing, as an approval checkpoint. The extracted record is the model's
 * suggestion (dashed violet) until the user approves the gate; only then does
 * the run continue to `commit`, which writes the Entry, the Document, the case,
 * its parties, citations and graph edges. After commit: confirmation + undo.
 */
const FIELD_FA: Record<string, string> = {
  title: 'عنوان', summary: 'خلاصه', kind: 'نوع', case_number: 'شمارهٔ پرونده', court: 'مرجع رسیدگی', branch: 'شعبه',
  topic: 'موضوع', status: 'وضعیت', case_type: 'نوع دعوا', insurance_line: 'رشتهٔ بیمه', claim_amount: 'مبلغ خواسته',
  outcome: 'نتیجه', filed_date: 'تاریخ طرح', stage: 'مرحله', group: 'گروه', date: 'تاریخ', year: 'سال',
}
const ROLE_FA: Record<string, string> = { khahan: 'خواهان', khande: 'خوانده', vakil_khahan: 'وکیل خواهان', vakil_khande: 'وکیل خوانده', ghazi: 'قاضی', mottaham: 'متهم', shaki: 'شاکی', other: 'سایر' }
const USED_BY_FA: Record<string, string> = { court: 'دادگاه', plaintiff: 'خواهان', defendant: 'خوانده', judge: 'قاضی', insurer: 'بیمه‌گر', insured: 'بیمه‌گذار', expert: 'کارشناس', lawyer: 'وکیل' }

type Draft = Record<string, unknown> & { entities?: Record<string, unknown> }
interface TimelineRow { date?: string; title?: string; detail?: string; source?: string }
interface SimilarRow { title: string; outcome?: string; why?: string; keep?: boolean; score?: number | null; entry_id?: string; document_id?: string }
interface RefRow { law?: string; article?: string; context?: string; used_by?: string; keep?: boolean; resolved?: boolean; ref_id?: string | null }

export function RunCard({ runId, compact }: { runId: string; compact?: boolean }) {
  const run = useAssistant((s) => s.runs[runId])
  const committed = useAssistant((s) => s.committed[runId])
  const busy = useAssistant((s) => s.busy)
  // List endpoints return run summaries without steps; fetch the full view.
  useEffect(() => { if (!run || !Array.isArray(run.steps)) void syncRun(runId) }, [run, runId])
  if (!run || !Array.isArray(run.steps)) return <div className="flex items-center gap-2 text-xs text-white/40"><Loader2 className="h-3.5 w-3.5 animate-spin" /> در حال بارگذاری اجرا…</div>

  const awaiting = run.steps.find((s) => s.status === 'awaiting_input')
  const failed = run.steps.find((s) => s.status === 'failed')
  const isCommitted = run.status === 'committed'
  const live = !isCommitted && run.status !== 'abandoned'

  return (
    <motion.div layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
      className={cn('overflow-hidden rounded-3xl', isCommitted ? 'border border-emerald-300/20 bg-emerald-400/[.04]' : live ? 'suggested' : 'border border-white/[.07] bg-white/[.02]')}>
      <div className="flex items-start justify-between gap-3 px-4 pt-4">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-medium">
            {isCommitted ? <span className="flex items-center gap-1 text-emerald-200/85"><ShieldCheck className="h-3.5 w-3.5" /> ثبت‌شده در آرشیو</span>
              : <span className="flex items-center gap-1 text-violet-200/85"><Sparkles className="h-3.5 w-3.5" /> پیش‌نویس دستیار — هنوز ثبت نشده</span>}
          </div>
          <div className="mt-1 truncate text-sm font-medium text-white/90">{asText(((run.state.draft as Draft | undefined)?.title)) || (run.raw_text ?? '').split('\n')[0].slice(0, 80)}</div>
        </div>
        <StatusPill run={run} />
      </div>
      <div className="space-y-3 px-4 pb-4 pt-3">
        <RunStepper run={run} compact={compact} />
        {awaiting && <Gate run={run} step={awaiting} busy={busy} />}
        {failed && !awaiting && (
          <div className="space-y-2">
            <div className="rounded-2xl border border-rose-300/15 bg-rose-400/[.06] px-3 py-2 text-[12px] text-rose-100/90">گام «{failed.label}» ناموفق بود — {failed.error}</div>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={() => void retryRun(run.id)}><RotateCcw className="h-3.5 w-3.5" /> تلاش دوباره</Button>
              <Button size="sm" variant="danger" onClick={() => void abandonRun(run.id)}><Ban className="h-3.5 w-3.5" /> توقف</Button>
            </div>
          </div>
        )}
        {run.status === 'running' && !awaiting && !failed && (
          <div className="flex items-center justify-between gap-2 text-xs text-white/50">
            <span className="flex items-center gap-2"><Loader2 className="h-3.5 w-3.5 animate-spin" /> خط لوله در حال اجراست…</span>
            <Button size="sm" variant="ghost" onClick={() => void retryRun(run.id)}>ادامه</Button>
          </div>
        )}
        {isCommitted && <Committed run={run} undone={committed?.undone} canUndo={!!committed && !committed.undone} />}
        {run.status === 'abandoned' && <div className="text-[12px] text-white/45">این ثبت متوقف شد — چیزی در آرشیو نوشته نشد.</div>}
      </div>
    </motion.div>
  )
}

function StatusPill({ run }: { run: EntryRun }) {
  const awaiting = run.steps.some((s) => s.status === 'awaiting_input')
  if (run.status === 'committed') return <Pill tone="good" dot>ثبت شد</Pill>
  if (run.status === 'abandoned') return <Pill>متوقف</Pill>
  if (run.status === 'failed') return <Pill tone="bad" dot>ناموفق</Pill>
  if (awaiting) return <Pill tone="warn" dot>در انتظار تأیید</Pill>
  return <Pill tone="info" dot>در حال اجرا</Pill>
}

function Committed({ run, canUndo, undone }: { run: EntryRun; canUndo: boolean; undone?: boolean }) {
  const open = useShell((s) => s.open)
  const draft = (run.state.draft as Draft | undefined) ?? {}
  const number = asText(draft.entities?.case_number)
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 rounded-2xl border border-emerald-300/15 bg-emerald-300/[.05] px-3 py-2 text-[12px] text-emerald-100/85">
        <CircleCheck className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1">{undone ? 'این ثبت برگردانده شد — مدخل و سند آن حذف شدند.' : `مدخل ثبت شد · شناسه ${run.entry_id?.slice(0, 8)} · پرونده، اشخاص، استنادها و گراف همگام شدند.`}</span>
        {canUndo && <Button size="sm" variant="ghost" className="h-7 text-emerald-100/80" onClick={() => void undoCommit(run.id)}><Undo2 className="h-3.5 w-3.5" /> برگرداندن</Button>}
      </div>
      {!undone && (
        <div className="flex flex-wrap gap-2">
          {number && <Button size="sm" onClick={() => open('cases', { record: number, label: fa(number), origin: 'tab' })}><FolderOpen className="h-3.5 w-3.5" /> پروندهٔ {fa(number)}</Button>}
          {run.entry_id && <Button size="sm" variant="ghost" onClick={() => open('editor', { record: run.entry_id!, label: 'ویرایش مدخل', origin: 'tab' })}><PenLine className="h-3.5 w-3.5" /> ویرایش مدخل</Button>}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ gates

function Gate({ run, step, busy }: { run: EntryRun; step: RunStep; busy: boolean }) {
  const payload = step.payload as Record<string, unknown>
  const conversation = payload.mode === 'conversation'
  const review = step.step_id === 'labels' && (payload.mode === 'review' || conversation)
  const [draft, setDraft] = useState<Draft>(() => structuredClone((review ? payload.draft : step.step_id === 'extract' ? payload : run.state.draft) as Draft ?? {}))
  const [timeline, setTimeline] = useState<TimelineRow[]>(() => structuredClone(((review ? payload.timeline : (payload as { rows?: TimelineRow[] }).rows ?? run.state.timeline) as TimelineRow[]) ?? []))
  const [similar, setSimilar] = useState<SimilarRow[]>(() => structuredClone(((review ? payload.similar : (payload as { items?: SimilarRow[] }).items ?? run.state.similar) as SimilarRow[]) ?? []))
  const [labels, setLabels] = useState<string[]>(() => [...(((review || step.step_id === 'labels') ? payload.labels : run.state.labels) as string[] ?? [])])
  const [refs, setRefs] = useState<RefRow[]>(() => structuredClone(((review ? payload.references : step.step_id === 'references' ? (payload as { rows?: RefRow[] }).rows : run.state.references) as RefRow[]) ?? []))
  const [details, setDetails] = useState(step.step_id !== 'labels')
  const missing = (review ? (payload.missing as [string, string][]) : []) ?? []
  const [working, setWorking] = useState(false)

  const approve = async () => {
    const patch: Record<string, unknown> = review
      ? { draft, timeline, similar, labels, references: refs }
      : step.step_id === 'extract' ? { draft }
      : step.step_id === 'references' ? { references: refs }
      : step.step_id === 'timeline' ? { timeline }
      : step.step_id === 'similar' ? { similar }
      : step.step_id === 'labels' ? { labels } : {}
    setWorking(true)
    await approveGate(run.id, patch)
    setWorking(false)
  }

  const action = review ? 'تأیید و ثبت در آرشیو' : step.step_id === 'labels' ? 'تأیید برچسب‌ها و ثبت نهایی' : `تأیید «${step.label}» و ادامه`

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 rounded-xl border border-amber-300/15 bg-amber-300/[.05] px-3 py-1.5 text-[11.5px] text-amber-100/90">
        <Hand className="h-3.5 w-3.5" /> در انتظار تأیید شما — {review ? 'بازبینی نهایی و ثبت' : step.label}{conversation ? ' · حالت گفتگویی: می‌توانید در گفتگو هم پاسخ دهید' : ''}
      </div>

      {conversation && typeof payload.question === 'string' && payload.question && (
        <div className="rounded-2xl border border-white/[.07] bg-white/[.03] px-3 py-2 text-[12.5px] leading-6 text-white/80">{payload.question as string}</div>
      )}
      {(review || step.step_id === 'extract') && <DraftTicket draft={draft} />}

      {missing.length > 0 && (
        <div className="space-y-2 rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
          <div className="text-[11.5px] text-white/50">این‌ها در متن پیدا نشدند — اگر می‌دانید پر کنید (اختیاری):</div>
          {missing.map(([path, label]) => (
            <label key={path} className="block text-[11px] text-white/45">{label}
              <input className={FIELD} defaultValue={fieldValue(draft, path)} onChange={(e) => setDraft((d) => setField(d, path, e.target.value))} />
            </label>
          ))}
        </div>
      )}

      {review && (
        <button onClick={() => setDetails((v) => !v)} className="flex w-full items-center justify-between rounded-xl border border-white/[.06] bg-white/[.02] px-3 py-2 text-[11.5px] text-white/60 hover:text-white">
          <span>ویرایش جزئیات — فیلدها، مستندات ({fa(refs.length)})، خط زمان ({fa(timeline.length)})، مشابه‌ها ({fa(similar.length)})، برچسب‌ها ({fa(labels.length)})</span>
          <ChevronDown className={cn('h-4 w-4 transition', details && 'rotate-180')} />
        </button>
      )}
      <AnimatePresence initial={false}>
        {(details || !review) && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="space-y-3 overflow-hidden">
            {(review || step.step_id === 'extract') && <FieldsEditor draft={draft} onChange={setDraft} />}
            {(review || step.step_id === 'references') && <RefsEditor rows={refs} onChange={setRefs} />}
            {(review || step.step_id === 'timeline') && <TimelineEditor rows={timeline} onChange={setTimeline} />}
            {(review || step.step_id === 'similar') && <SimilarEditor rows={similar} onChange={setSimilar} />}
            {(review || step.step_id === 'labels') && <LabelsEditor labels={labels} onChange={setLabels} />}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex items-center gap-2 pt-1">
        <Button size="sm" variant="danger" onClick={() => void abandonRun(run.id)} disabled={working}><Ban className="h-3.5 w-3.5" /> توقف</Button>
        <Button size="sm" variant="approve" className="ms-auto" onClick={approve} disabled={working || busy}>
          {working ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} {action}
        </Button>
      </div>
    </div>
  )
}

const FIELD = 'mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs text-white outline-none focus:border-indigo-300/40'

function fieldValue(draft: Draft, path: string) {
  return path.startsWith('entities.') ? asText(draft.entities?.[path.slice(9)]) : asText(draft[path])
}
function setField(draft: Draft, path: string, value: string): Draft {
  if (path.startsWith('entities.')) return { ...draft, entities: { ...(draft.entities ?? {}), [path.slice(9)]: value } }
  return { ...draft, [path]: value }
}

/** The extracted record, drawn as the ticket it will become. */
function DraftTicket({ draft }: { draft: Draft }) {
  const e = draft.entities ?? {}
  const parties = (draft.parties as { name?: string; role?: string }[] | undefined) ?? []
  const events = (draft.events as { date?: string; description?: string }[] | undefined) ?? []
  const refs = (draft.legal_refs as { law?: string; article?: string }[] | undefined) ?? []
  const number = asText(e.case_number)
  const missing = [!asText(draft.title) && 'عنوان', !asText(draft.summary) && 'خلاصه', !number && 'شمارهٔ پرونده', !parties.length && 'طرفین'].filter(Boolean) as string[]
  return (
    <div className="space-y-2.5 rounded-2xl border border-white/[.06] bg-ink-900/40 p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-white/90">{asText(draft.title) || 'بدون عنوان'}</span>
        <span className="ltr rounded-md border border-violet-300/25 bg-violet-300/10 px-1.5 font-mono text-[11px] text-violet-100">{number ? fa(number) : '—'}</span>
      </div>
      {asText(draft.summary) && <p className="text-[12px] leading-6 text-white/60">{asText(draft.summary)}</p>}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11.5px] sm:grid-cols-3">
        {['court', 'topic', 'case_type', 'insurance_line', 'claim_amount', 'status'].filter((k) => asText(e[k])).map((k) => (
          <div key={k} className="min-w-0"><span className="text-white/35">{FIELD_FA[k]}: </span><span className="text-white/75">{fa(asText(e[k]))}</span></div>
        ))}
      </div>
      {parties.length > 0 && <div className="flex flex-wrap gap-1.5">{parties.map((p, i) => <span key={i} className="rounded-full border border-white/[.07] bg-white/[.03] px-2 py-0.5 text-[11px] text-white/70"><span className="text-white/35">{ROLE_FA[p.role ?? ''] ?? p.role}: </span>{p.name}</span>)}</div>}
      {refs.length > 0 && <div className="flex flex-wrap gap-1.5">{refs.map((r, i) => <span key={i} className="rounded-full border border-amber-300/15 bg-amber-300/[.06] px-2 py-0.5 text-[11px] text-amber-100/85">مادهٔ {fa(r.article ?? '')} {r.law}</span>)}</div>}
      {events.length > 0 && <div className="text-[11px] text-white/45">{events.slice(0, 3).map((ev, i) => <div key={i}>{fa(ev.date ?? '')} — {ev.description}</div>)}</div>}
      <div className="flex flex-wrap gap-1.5 pt-1">
        {missing.length ? missing.map((m) => <Pill key={m} tone="warn">{m} استخراج نشده</Pill>) : <Pill tone="good">کامل</Pill>}
      </div>
    </div>
  )
}

function FieldsEditor({ draft, onChange }: { draft: Draft; onChange: (d: Draft) => void }) {
  const plain = Object.entries(draft).filter(([, v]) => typeof v === 'string' || v == null)
  const ents = Object.entries(draft.entities ?? {}).filter(([, v]) => typeof v === 'string' || typeof v === 'number' || v == null)
  return (
    <Section title="فیلدهای مدخل">
      <div className="grid gap-2 sm:grid-cols-2">
        {plain.map(([k, v]) => (
          <label key={k} className={cn('text-[11px] text-white/45', k === 'summary' && 'sm:col-span-2')}>{FIELD_FA[k] ?? k}
            {k === 'summary' ? <textarea rows={3} className={cn(FIELD, 'h-auto py-2 leading-6')} value={asText(v)} onChange={(e) => onChange({ ...draft, [k]: e.target.value })} />
              : <input className={FIELD} value={asText(v)} onChange={(e) => onChange({ ...draft, [k]: e.target.value })} />}
          </label>
        ))}
        {ents.map(([k, v]) => (
          <label key={k} className="text-[11px] text-white/45">{FIELD_FA[k] ?? k}
            <input className={FIELD} value={asText(v)} onChange={(e) => onChange({ ...draft, entities: { ...(draft.entities ?? {}), [k]: e.target.value } })} />
          </label>
        ))}
      </div>
    </Section>
  )
}

function RefsEditor({ rows, onChange }: { rows: RefRow[]; onChange: (r: RefRow[]) => void }) {
  const set = (i: number, patch: Partial<RefRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <Section title="مستندات قانونی" hint="موارد نامرتبط را بردارید؛ قانون و ماده را در صورت نیاز اصلاح کنید.">
      {!rows.length && <div className="text-[11.5px] text-white/35">مستندی استخراج نشد.</div>}
      {rows.map((r, i) => (
        <div key={i} className={cn('grid grid-cols-[auto_1fr_80px] items-center gap-2 rounded-xl border px-2 py-1.5', r.keep === false ? 'border-white/[.04] opacity-50' : 'border-white/[.07]')}>
          <input type="checkbox" checked={r.keep !== false} onChange={(e) => set(i, { keep: e.target.checked })} className="accent-emerald-300" aria-label="نگه‌داری" />
          <input className="h-8 min-w-0 rounded-lg border border-white/10 bg-white/[.03] px-2 text-[11.5px] outline-none" value={r.law ?? ''} onChange={(e) => set(i, { law: e.target.value })} aria-label="قانون" />
          <input className="h-8 rounded-lg border border-white/10 bg-white/[.03] px-2 text-center text-[11.5px] outline-none" value={r.article ?? ''} onChange={(e) => set(i, { article: e.target.value })} aria-label="ماده" />
          <div className="col-span-3 flex flex-wrap gap-2 ps-6 text-[10.5px] text-white/40">
            {r.resolved ? <span className="text-emerald-200/70">✓ در پایگاه قوانین یافت شد</span> : <span className="text-amber-200/70">! در پایگاه قوانین نیست — به‌صورت پیش‌نویس ثبت می‌شود</span>}
            {r.used_by && <span>استنادکننده: {USED_BY_FA[r.used_by] ?? r.used_by}</span>}
            {r.context && <span>{r.context}</span>}
          </div>
        </div>
      ))}
      <Button size="sm" variant="ghost" onClick={() => onChange([...rows, { law: '', article: '', keep: true, used_by: 'court' }])}><Plus className="h-3.5 w-3.5" /> افزودن مستند</Button>
    </Section>
  )
}

function TimelineEditor({ rows, onChange }: { rows: TimelineRow[]; onChange: (r: TimelineRow[]) => void }) {
  const set = (i: number, patch: Partial<TimelineRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <Section title="خط زمان" hint="خط زمانِ تأییدشده، رویدادهای مدخل را تعیین می‌کند.">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[96px_1fr_auto] gap-2">
          <input className="h-8 rounded-lg border border-white/10 bg-white/[.03] px-2 text-[11.5px] outline-none" placeholder="۱۴۰۳/۰۷/۰۵" value={r.date ?? ''} onChange={(e) => set(i, { date: e.target.value })} aria-label="تاریخ" />
          <input className="h-8 min-w-0 rounded-lg border border-white/10 bg-white/[.03] px-2 text-[11.5px] outline-none" placeholder="رویداد" value={r.title ?? ''} onChange={(e) => set(i, { title: e.target.value })} aria-label="رویداد" />
          <button onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label="حذف" className="flex h-8 w-8 items-center justify-center rounded-lg text-white/35 hover:bg-white/[.05] hover:text-white"><Trash2 className="h-3.5 w-3.5" /></button>
        </div>
      ))}
      <Button size="sm" variant="ghost" onClick={() => onChange([...rows, { date: '', title: '' }])}><Plus className="h-3.5 w-3.5" /> افزودن رویداد</Button>
    </Section>
  )
}

function SimilarEditor({ rows, onChange }: { rows: SimilarRow[]; onChange: (r: SimilarRow[]) => void }) {
  return (
    <Section title="پرونده‌های مشابه" hint="تیک موارد نامرتبط را بردارید — موارد نگه‌داشته به این مدخل پیوند می‌خورند.">
      {!rows.length && <div className="text-[11.5px] text-white/35">موردی یافت نشد — می‌توانید بدون پیوند ادامه دهید.</div>}
      {rows.map((r, i) => (
        <label key={i} className={cn('flex cursor-pointer items-start gap-2 rounded-xl border px-2.5 py-2 text-[11.5px]', r.keep === false ? 'border-white/[.04] opacity-50' : 'border-white/[.07]')}>
          <input type="checkbox" className="mt-1 accent-emerald-300" checked={r.keep !== false} onChange={(e) => onChange(rows.map((x, j) => (j === i ? { ...x, keep: e.target.checked } : x)))} />
          <span className="min-w-0">
            <span className="block text-white/80">{r.title}</span>
            {r.outcome && <span className="block text-white/40">نتیجه: {r.outcome}</span>}
            {r.why && <span className="block text-white/30">علت پیوند: {r.why}</span>}
          </span>
        </label>
      ))}
    </Section>
  )
}

function LabelsEditor({ labels, onChange }: { labels: string[]; onChange: (l: string[]) => void }) {
  const { data: options } = useOptions()
  const [value, setValue] = useState('')
  const suggestions = useMemo(() => (options?.taxonomy_leaves ?? []).filter((l) => !labels.includes(l)).slice(0, 12), [options, labels])
  const add = (l: string) => { const t = l.trim(); if (t && !labels.includes(t)) onChange([...labels, t]); setValue('') }
  return (
    <Section title="برچسب‌ها" hint="بردارید یا اضافه کنید.">
      <div className="flex flex-wrap gap-1.5">
        {labels.map((l) => (
          <button key={l} onClick={() => onChange(labels.filter((x) => x !== l))} className="rounded-full border border-cyan-300/20 bg-cyan-300/[.08] px-2.5 py-0.5 text-[11.5px] text-cyan-100 hover:line-through">{l} ×</button>
        ))}
        <input value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), add(value))} placeholder="برچسب جدید…" className="h-7 w-32 rounded-full border border-white/10 bg-white/[.03] px-3 text-[11.5px] outline-none" />
      </div>
      {suggestions.length > 0 && <div className="flex flex-wrap gap-1.5">{suggestions.map((s) => <button key={s} onClick={() => add(s)} className="rounded-full border border-dashed border-white/15 px-2 py-0.5 text-[11px] text-white/45 hover:text-white">+ {s}</button>)}</div>}
    </Section>
  )
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
      <div className="flex items-baseline justify-between gap-2"><span className="text-[12px] font-medium text-white/75">{title}</span>{hint && <span className="text-[10.5px] text-white/30">{hint}</span>}</div>
      {children}
    </div>
  )
}
