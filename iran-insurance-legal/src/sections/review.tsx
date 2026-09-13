import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Flag, Loader2, Save } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive, useRefreshArchive } from '@/api/queries'
import type { LegalCase } from '@/api/types'
import { fa } from '@/lib/format'
import { asText } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, Empty, Pill } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/**
 * ۰۹ بازبینی انسانی — cases the extractor could not complete (no case number
 * or no parties). Fixing one edits its entry; approving or flagging records a
 * `review` label that feeds evaluation.
 */
export function ReviewView(_: { ws: WorkspaceTab }) {
  const { data, error, refetch } = useArchive()
  usePublishContext('review', {})
  if (error) return <LoadError error={error} retry={() => void refetch()} />
  if (!data) return <Skeleton />
  const queue = data.review_queue
  return (
    <>
      <PageHeader eyebrow="۰۹ · بازبینی انسانی" title="بازبینی انسانی" summary="پرونده وقتی ناقص شمرده می‌شود که شمارهٔ پرونده یا طرفین از متن استخراج نشده باشد. اصلاح شما مدخل را به‌روز و پرونده را دوباره همگام می‌کند." right={<Pill tone={queue.length ? 'warn' : 'good'}>{fa(queue.length)} پرونده ناقص</Pill>} />
      <div className="mt-6 space-y-4">
        {queue.map((c) => <ReviewCard key={c.id} c={c} />)}
        {!queue.length && <Card><Empty icon={<CheckCircle2 className="h-5 w-5" />} title="صف خالی است — همهٔ پرونده‌ها کامل‌اند" /></Card>}
      </div>
    </>
  )
}

function ReviewCard({ c }: { c: LegalCase }) {
  const entry = c.entries[0]
  const e = entry.entities ?? {}
  const refresh = useRefreshArchive()
  const open = useShell((s) => s.open)
  const [f, setF] = useState({ title: entry.title ?? '', case_number: asText(e.case_number), court: asText(e.court), topic: asText(e.topic), branch: asText(e.branch), year: asText(e.year) })
  const [note, setNote] = useState('')
  const [previewing, setPreviewing] = useState(false)
  const toast = useAssistant.getState().toast
  const save = useMutation({
    mutationFn: () => api.patchEntry(entry.id, { title: f.title, entities: { case_number: f.case_number, court: f.court, topic: f.topic, branch: f.branch, year: f.year } }),
    onSuccess: () => { toast({ tone: 'success', title: 'اصلاحات ذخیره شد', detail: 'پرونده دوباره همگام شد.', undo: async () => { await api.patchEntry(entry.id, { title: entry.title, entities: e }); void refresh() } }); useAssistant.getState().log({ kind: 'saved', text: `بازبینی «${f.title}» ذخیره شد`, refs: [entry.id] }); setPreviewing(false); void refresh() },
  })
  const label = useMutation({
    mutationFn: (value: 'ok' | 'problem') => api.addLabel({ kind: 'review', target_type: 'entry', target_id: entry.id, value, note: note || null }),
    onSuccess: (_, value) => toast({ tone: value === 'ok' ? 'success' : 'info', title: value === 'ok' ? 'به‌عنوان بازبینی‌شده ثبت شد' : 'مشکل ثبت شد' }),
  })
  const field = 'mt-1 h-9 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-[12.5px] outline-none focus:border-indigo-300/40'
  const L = (k: keyof typeof f, label: string) => <label className="text-[11.5px] text-white/45">{label}<input className={field} value={f[k]} onChange={(ev) => setF({ ...f, [k]: ev.target.value })} /></label>
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><div className="text-[14px] font-medium text-white/90">{fa(c.title)}</div><div className="mt-1 flex flex-wrap gap-1.5">{c.incomplete_reasons.map((r) => <Pill key={r} tone="warn">{r}</Pill>)}</div></div>
        <Button size="sm" variant="ghost" onClick={() => open('editor', { record: entry.id, label: 'ویرایش مدخل' })}>ویرایش کامل</Button>
      </div>
      <p className="mt-3 line-clamp-3 rounded-2xl border border-white/[.05] bg-white/[.02] p-3 text-[12px] leading-6 text-white/50">{fa(c.text.slice(0, 400))}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">{L('title', 'عنوان')}{L('case_number', 'شمارهٔ پرونده')}{L('court', 'مرجع')}{L('topic', 'موضوع')}{L('branch', 'شعبه')}{L('year', 'سال')}</div>
      <label className="mt-3 block text-[11.5px] text-white/45">یادداشت بازبینی<input className={field} value={note} onChange={(ev) => setNote(ev.target.value)} /></label>
      {previewing && <div className="suggested mt-3 rounded-2xl p-3 text-[12px] leading-6 text-violet-50/85">ذخیره می‌شود: {f.case_number ? <>شمارهٔ پرونده <b>{fa(f.case_number)}</b></> : 'بدون شمارهٔ پرونده'}{f.court ? ` · ${f.court}` : ''}{f.topic ? ` · ${f.topic}` : ''}. {f.case_number ? 'پرونده ساخته یا به پروندهٔ هم‌شماره پیوند می‌خورد.' : ''}</div>}
      {(save.error || label.error) && <div className="mt-2 text-[12px] text-rose-200/80">{describeError(save.error ?? label.error)}</div>}
      <div className="mt-4 flex flex-wrap gap-2">
        {!previewing ? <Button variant="primary" onClick={() => setPreviewing(true)}><Save className="h-4 w-4" /> ذخیرهٔ اصلاحات</Button> : <Button variant="approve" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} تأیید و ذخیره</Button>}
        <Button onClick={() => label.mutate('ok')} disabled={label.isPending}><CheckCircle2 className="h-4 w-4" /> تأیید بدون تغییر</Button>
        <Button variant="danger" onClick={() => label.mutate('problem')} disabled={label.isPending}><Flag className="h-4 w-4" /> علامت‌گذاری مشکل‌دار</Button>
      </div>
    </Card>
  )
}
