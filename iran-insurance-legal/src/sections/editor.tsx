import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, FolderOpen, Loader2, Plus, Save, Search, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive, useOptions, useRefreshArchive } from '@/api/queries'
import type { CaseEntry, EntryLegalRef, Party, Representation } from '@/api/types'
import { date, fa } from '@/lib/format'
import { asText, cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'
import { ROLE_FA } from './cases'

/**
 * ۱۷ ویرایش مدخل‌ها — full edit of an entry: fields, parties, representation,
 * events, legal references, tags. Saving re-syncs the case, persons, citations
 * and graph (`catalog.update_entry`); every save shows exactly what changes
 * first, and can be undone. Delete removes the entry (and optionally its
 * document), its case when empty, and orphaned persons.
 */
export function EditorView({ ws }: { ws: WorkspaceTab }) {
  if (ws.active) return <EntryEditor id={ws.active} />
  return <EntryList query={ws.query ?? ''} />
}

function EntryList({ query }: { query: string }) {
  const { data, error } = useArchive()
  const { setQuery, openInner } = useShell()
  usePublishContext('editor', { filters: query ? { جستجو: query } : undefined })
  const rows = useMemo(() => (data?.entries ?? []).filter((e) => !query || `${e.title} ${e.summary} ${asText(e.entities?.case_number)}`.includes(query)), [data, query])
  if (error) return <LoadError error={error} />
  if (!data) return <Skeleton />
  return (
    <>
      <PageHeader eyebrow="۱۷ · ویرایش مدخل‌ها" title="ویرایش مدخل‌ها" summary="هر مدخل را کامل ویرایش کنید؛ ذخیره، پرونده، اشخاص، استنادها و گراف را دوباره همگام می‌کند." right={<Pill>{fa(rows.length)} مدخل</Pill>} />
      <div className="glass mt-5 flex items-center gap-2 rounded-2xl px-3"><Search className="h-4 w-4 text-white/35" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="عنوان، خلاصه یا شمارهٔ پرونده…" className="h-10 flex-1 bg-transparent text-[13px] outline-none" /></div>
      <Card className="mt-4 divide-y divide-white/[.05]">
        {rows.slice(0, 120).map((e) => (
          <button key={e.id} onClick={() => openInner(e.id, (e.title || 'مدخل').slice(0, 22))} className="flex w-full items-center gap-4 px-5 py-3 text-start transition hover:bg-white/[.025]">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] text-white/85">{fa(e.title || 'بدون عنوان')}</div>
              <div className="truncate text-[11.5px] text-white/40">{fa(asText(e.entities?.case_number) || 'بدون شماره')} · {date(e.created_at)}</div>
            </div>
            <ArrowLeft className="h-4 w-4 text-white/25" />
          </button>
        ))}
        {!rows.length && <Empty title="مدخلی یافت نشد" />}
      </Card>
    </>
  )
}

type Form = { title: string; summary: string; kind: string; entities: Record<string, string>; parties: Party[]; representation: Representation[]; events: { date: string; description: string }[]; legal_refs: EntryLegalRef[]; tags: string }

const toForm = (e: CaseEntry): Form => ({
  title: e.title ?? '', summary: e.summary ?? '', kind: e.kind ?? 'session',
  entities: Object.fromEntries(Object.entries(e.entities ?? {}).filter(([, v]) => typeof v !== 'object' || v === null).map(([k, v]) => [k, asText(v)])),
  parties: (e.parties ?? []).map((p) => (typeof p === 'string' ? { name: p, role: 'other' } : p)),
  representation: e.representation ?? [],
  events: (e.events ?? []).map((ev) => (typeof ev === 'string' ? { date: '', description: ev } : { date: ev.date ?? '', description: asText(ev.description ?? ev.what ?? ev.type) })),
  legal_refs: (e.legal_refs ?? []).map((r) => ({ law: r.law ?? '', article: r.article ?? '', context: r.context ?? '', used_by: r.used_by ?? 'court' })),
  tags: (e.tags ?? []).join('، '),
})
const toPatch = (f: Form) => ({ ...f, tags: f.tags.split(/[،,]/).map((t) => t.trim()).filter(Boolean) })

const LABEL: Record<string, string> = { case_number: 'شمارهٔ پرونده', court: 'مرجع رسیدگی', topic: 'موضوع', case_type: 'نوع دعوا', insurance_line: 'رشتهٔ بیمه', claim_amount: 'مبلغ خواسته', status: 'وضعیت', filed_date: 'تاریخ طرح', stage: 'مرحله', outcome: 'نتیجه', group: 'گروه', branch: 'شعبه' }

function EntryEditor({ id }: { id: string }) {
  const entry = useQuery({ queryKey: ['entry', id], queryFn: () => api.entry(id) })
  const { data: options } = useOptions()
  const refresh = useRefreshArchive()
  const { open, closeInner } = useShell()
  const [form, setForm] = useState<Form | null>(null)
  const [review, setReview] = useState(false)
  const [del, setDel] = useState<null | 'ask' | 'with-doc' | 'entry-only'>(null)
  useEffect(() => { if (entry.data) setForm(toForm(entry.data)) }, [entry.data])
  usePublishContext('editor', { entityKind: 'entry', entityLabel: entry.data?.title?.slice(0, 30), view: 'ویرایش' })

  const original = entry.data ? toForm(entry.data) : null
  const changes = useMemo(() => {
    if (!form || !original) return []
    const out: [string, string, string][] = []
    ;(['title', 'summary', 'kind', 'tags'] as const).forEach((k) => { if (form[k] !== original[k]) out.push([({ title: 'عنوان', summary: 'خلاصه', kind: 'نوع', tags: 'برچسب‌ها' })[k], String(original[k]).slice(0, 60), String(form[k]).slice(0, 60)]) })
    Object.keys({ ...form.entities, ...original.entities }).forEach((k) => { if ((form.entities[k] ?? '') !== (original.entities[k] ?? '')) out.push([LABEL[k] ?? k, original.entities[k] ?? '—', form.entities[k] ?? '—']) })
    ;(['parties', 'representation', 'events', 'legal_refs'] as const).forEach((k) => { if (JSON.stringify(form[k]) !== JSON.stringify(original[k])) out.push([({ parties: 'طرفین', representation: 'وکالت', events: 'رویدادها', legal_refs: 'مستندات قانونی' })[k], `${fa(original[k].length)} مورد`, `${fa(form[k].length)} مورد`]) })
    return out
  }, [form, original])

  const save = useMutation({
    mutationFn: () => api.patchEntry(id, toPatch(form!)),
    onSuccess: (saved) => {
      const before = original!
      useAssistant.getState().toast({ tone: 'success', title: 'مدخل ذخیره شد', detail: 'پرونده، اشخاص، استنادها و گراف دوباره همگام شدند.', undo: async () => { await api.patchEntry(id, toPatch(before)); void entry.refetch(); void refresh(); useAssistant.getState().toast({ tone: 'info', title: 'ویرایش برگردانده شد' }) } })
      useAssistant.getState().log({ kind: 'saved', text: `مدخل «${saved.title}» ویرایش شد (${changes.length} تغییر)`, refs: [id] })
      setReview(false); void entry.refetch(); void refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (withDoc: boolean) => api.deleteEntry(id, withDoc),
    onSuccess: () => { useAssistant.getState().toast({ tone: 'info', title: 'مدخل حذف شد' }); useAssistant.getState().log({ kind: 'deleted', text: `مدخل «${entry.data?.title}» حذف شد`, refs: [id] }); void refresh(); closeInner(id) },
  })

  if (entry.error) return <LoadError error={entry.error} retry={() => void entry.refetch()} />
  if (!entry.data || !form) return <Skeleton />
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch })
  const input = 'h-9 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-[12.5px] outline-none focus:border-indigo-300/40'
  const num = asText(entry.data.entities?.case_number)

  return (
    <>
      <PageHeader eyebrow="۱۷ · ویرایش مدخل" title={fa(form.title || 'بدون عنوان')} summary={`ثبت ${date(entry.data.created_at)}${num ? ` · پروندهٔ ${fa(num)}` : ''}`}
        right={<>{num && <Button onClick={() => open('cases', { record: num, label: fa(num) })}><FolderOpen className="h-4 w-4" /> پروندهٔ حاصل</Button>}<Button variant="primary" disabled={!changes.length} onClick={() => setReview(true)}><Save className="h-4 w-4" /> ذخیره ({fa(changes.length)})</Button></>} />

      {review && (
        <Card className="suggested mt-5 p-5">
          <div className="text-sm font-medium">پیش‌نمایش تغییرات</div>
          <ul className="mt-3 divide-y divide-white/[.06] text-[12.5px]">
            {changes.map(([f, a, b], i) => <li key={i} className="grid grid-cols-[140px_1fr] gap-3 py-2"><span className="text-white/45">{f}</span><span><span className="text-white/35 line-through decoration-white/20">{fa(a) || '—'}</span> ← <span className="text-violet-100">{fa(b) || '—'}</span></span></li>)}
          </ul>
          <p className="mt-2 text-[11px] text-white/40">پس از ذخیره، هر ارجاع به پایگاه قوانین متصل می‌شود؛ ماده‌ای که در پایگاه نباشد به‌صورت «حل‌نشده» ثبت می‌شود.</p>
          {save.error && <div className="mt-2 text-[12px] text-rose-200/80">{describeError(save.error)}</div>}
          <div className="mt-3 flex gap-2"><Button variant="ghost" onClick={() => setReview(false)}>ادامهٔ ویرایش</Button><Button variant="approve" disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} تأیید و ذخیره</Button></div>
        </Card>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          <Card className="space-y-3 p-5">
            <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
              <label className="text-[11.5px] text-white/45">عنوان<input className={cn(input, 'mt-1')} value={form.title} onChange={(e) => set({ title: e.target.value })} /></label>
              <label className="text-[11.5px] text-white/45">نوع<select className={cn(input, 'mt-1')} value={form.kind} onChange={(e) => set({ kind: e.target.value })}><option value="session">صورت‌جلسه</option><option value="note">یادداشت</option></select></label>
            </div>
            <label className="block text-[11.5px] text-white/45">چکیده<textarea rows={4} className={cn(input, 'mt-1 h-auto py-2 leading-7')} value={form.summary} onChange={(e) => set({ summary: e.target.value })} /></label>
            <div className="grid gap-3 sm:grid-cols-3">
              {Object.keys({ case_number: '', court: '', topic: '', case_type: '', insurance_line: '', status: '', claim_amount: '', filed_date: '', outcome: '', ...form.entities }).filter((k) => !['people', 'orgs'].includes(k)).map((k) => (
                <label key={k} className={cn('text-[11.5px] text-white/45', k === 'outcome' && 'sm:col-span-3')}>{LABEL[k] ?? k}
                  {k === 'case_type' || k === 'insurance_line' ? (
                    <select className={cn(input, 'mt-1')} value={form.entities[k] ?? ''} onChange={(e) => set({ entities: { ...form.entities, [k]: e.target.value } })}>
                      <option value="">—</option>{(k === 'case_type' ? options?.case_types : options?.insurance_lines)?.map((o) => <option key={o}>{o}</option>)}
                      {form.entities[k] && !(k === 'case_type' ? options?.case_types : options?.insurance_lines)?.includes(form.entities[k]) && <option>{form.entities[k]}</option>}
                    </select>
                  ) : <input className={cn(input, 'mt-1')} value={form.entities[k] ?? ''} onChange={(e) => set({ entities: { ...form.entities, [k]: e.target.value } })} />}
                </label>
              ))}
            </div>
            <label className="block text-[11.5px] text-white/45">برچسب‌ها (با ویرگول جدا کنید)<input className={cn(input, 'mt-1')} value={form.tags} onChange={(e) => set({ tags: e.target.value })} /></label>
          </Card>
          <ListEditor title="طرفین" rows={form.parties} empty={{ name: '', role: 'other' }} onChange={(parties) => set({ parties })} render={(p, upd) => (<>
            <input className={input} placeholder="نام" value={p.name} onChange={(e) => upd({ name: e.target.value })} />
            <select className={cn(input, 'w-40')} value={p.role} onChange={(e) => upd({ role: e.target.value })}>{Object.entries(ROLE_FA).slice(0, 8).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </>)} />
          <ListEditor title="وکالت" rows={form.representation} empty={{ lawyer: '', client: '' }} onChange={(representation) => set({ representation })} render={(r, upd) => (<>
            <input className={input} placeholder="وکیل" value={r.lawyer ?? ''} onChange={(e) => upd({ lawyer: e.target.value })} />
            <input className={input} placeholder="موکل" value={r.client ?? ''} onChange={(e) => upd({ client: e.target.value })} />
          </>)} />
          <ListEditor title="رویدادها" rows={form.events} empty={{ date: '', description: '' }} onChange={(events) => set({ events })} render={(ev, upd) => (<>
            <input className={cn(input, 'w-32')} placeholder="۱۴۰۳/۰۷/۰۵" value={ev.date} onChange={(e) => upd({ date: e.target.value })} />
            <input className={input} placeholder="شرح" value={ev.description} onChange={(e) => upd({ description: e.target.value })} />
          </>)} />
          <ListEditor title="مستندات قانونی" rows={form.legal_refs} empty={{ law: '', article: '', context: '', used_by: 'court' }} onChange={(legal_refs) => set({ legal_refs })} render={(r, upd) => (<>
            <input className={input} placeholder="قانون" value={r.law ?? ''} onChange={(e) => upd({ law: e.target.value })} />
            <input className={cn(input, 'w-24')} placeholder="ماده" value={r.article ?? ''} onChange={(e) => upd({ article: e.target.value })} />
            <input className={input} placeholder="زمینهٔ استناد" value={r.context ?? ''} onChange={(e) => upd({ context: e.target.value })} />
          </>)} />
        </div>
        <div className="space-y-5">
          <Card><CardHeader title="متن خام" /><div className="max-h-96 overflow-y-auto whitespace-pre-wrap px-5 pb-5 text-[12.5px] leading-7 text-white/55">{entry.data.raw_text ?? '—'}</div></Card>
          <Card className="p-5">
            <div className="text-sm font-medium text-rose-100/90">حذف مدخل</div>
            <p className="mt-1 text-[11.5px] leading-6 text-white/45">مدخل، پروندهٔ آن اگر خالی شود و اشخاص یتیم حذف می‌شوند. برگشت‌پذیر نیست.</p>
            {!del ? <Button className="mt-3" variant="danger" onClick={() => setDel('ask')}><Trash2 className="h-4 w-4" /> حذف…</Button> : (
              <div className="mt-3 space-y-2">
                <label className="flex items-center gap-2 text-[12px] text-white/60"><input type="radio" name="del" checked={del === 'entry-only'} onChange={() => setDel('entry-only')} /> فقط مدخل</label>
                <label className="flex items-center gap-2 text-[12px] text-white/60"><input type="radio" name="del" checked={del === 'with-doc'} onChange={() => setDel('with-doc')} /> مدخل و سند آن</label>
                <div className="flex gap-2"><Button size="sm" variant="ghost" onClick={() => setDel(null)}>انصراف</Button><Button size="sm" variant="danger" disabled={del === 'ask' || remove.isPending} onClick={() => remove.mutate(del === 'with-doc')}>{remove.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />} تأیید حذف</Button></div>
                {remove.error && <div className="text-[11.5px] text-rose-200/80">{describeError(remove.error)}</div>}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}

function ListEditor<T>({ title, rows, empty, onChange, render }: { title: string; rows: T[]; empty: T; onChange: (rows: T[]) => void; render: (row: T, update: (patch: Partial<T>) => void) => React.ReactNode }) {
  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between"><div className="text-sm font-medium">{title} <span className="text-white/35">({fa(rows.length)})</span></div><Button size="sm" variant="ghost" onClick={() => onChange([...rows, structuredClone(empty)])}><Plus className="h-3.5 w-3.5" /> افزودن</Button></div>
      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            {render(row, (patch) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r))))}
            <button onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label="حذف" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white/35 hover:bg-white/[.05] hover:text-white"><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
        ))}
        {!rows.length && <div className="text-xs text-white/35">موردی ثبت نشده است.</div>}
      </div>
    </Card>
  )
}
