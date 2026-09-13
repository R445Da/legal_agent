import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Loader2, Search, Tag, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { useArchive, useRefreshArchive } from '@/api/queries'
import type { ArchiveDocument } from '@/api/types'
import { date, fa } from '@/lib/format'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/segmented'
import { Chips, KV } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

const PAGE = 20
const FACET_FA: Record<string, string> = { year: 'سال', group: 'گروه', doc_kind: 'نوع سند', branch: 'شعبه', status: 'وضعیت' }
const STATUS_FA: Record<string, string> = { new: 'جدید', open: 'باز', reviewed: 'بازبینی‌شده', closed: 'بسته' }

/** ۰۷ تیکت‌ها (اسناد) — every ingested document, browsable and openable in place. */
export function DocumentsView({ ws }: { ws: WorkspaceTab }) {
  if (ws.active) return <DocumentFile id={ws.active} />
  return <DocumentList query={ws.query ?? ''} />
}

function DocumentList({ query }: { query: string }) {
  const { data: state } = useArchive()
  const { setQuery, openInner } = useShell()
  const [offset, setOffset] = useState(0)
  const [collection, setCollection] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  usePublishContext('documents', { filters: Object.fromEntries([...Object.entries(filters).filter(([, v]) => v).map(([k, v]) => [FACET_FA[k] ?? k, v]), ...(query ? [['جستجو', query]] : [])]) })
  const page = useQuery({ queryKey: ['documents', query, collection, filters, offset], queryFn: () => api.documents({ q: query || undefined, limit: PAGE, offset, collection: collection || undefined, ...filters }) })
  const select = 'h-10 rounded-2xl border border-white/10 bg-white/[.04] px-3 text-xs text-white/75 outline-none'
  return (
    <>
      <PageHeader eyebrow="۰۷ · تیکت‌ها (اسناد)" title="اسناد" summary="هر سند یک تیکت است — متن کامل، قطعه‌هایی که بازیاب ذخیره کرده و فرادادهٔ استخراج‌شده." right={page.data && <Pill>{fa(page.data.total)} سند</Pill>} />
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="glass flex min-w-[240px] flex-1 items-center gap-2 rounded-2xl px-3">
          <Search className="h-4 w-4 text-white/35" />
          <input value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }} placeholder="عنوان، منبع یا متن…" className="h-10 flex-1 bg-transparent text-[13px] outline-none placeholder:text-white/25" />
        </div>
        <select className={select} value={collection} onChange={(e) => { setCollection(e.target.value); setOffset(0) }} aria-label="مجموعه"><option value="">همهٔ مجموعه‌ها</option>{state?.collections.map((c) => <option key={c.name} value={c.name}>{c.name} ({fa(c.documents)})</option>)}</select>
        {state && Object.entries(state.facets).filter(([, v]) => v.length).map(([key, values]) => (
          <select key={key} className={select} value={filters[key] ?? ''} onChange={(e) => { setFilters({ ...filters, [key]: e.target.value }); setOffset(0) }} aria-label={FACET_FA[key] ?? key}>
            <option value="">{FACET_FA[key] ?? key}: همه</option>{values.map((v) => <option key={v.value} value={v.value}>{fa(v.value)} ({fa(v.documents)})</option>)}
          </select>
        ))}
      </div>
      {page.error ? <LoadError error={page.error} retry={() => void page.refetch()} /> : !page.data ? <Skeleton /> : (
        <>
          <Card className="mt-4 divide-y divide-white/[.05]">
            {page.data.items.map((d) => <DocRow key={d.id} d={d} onOpen={() => openInner(d.id, (d.title ?? d.source).slice(0, 24))} />)}
            {!page.data.items.length && <Empty title="سندی یافت نشد" />}
          </Card>
          <div className="mt-4 flex items-center justify-between text-xs text-white/45">
            <span>{fa(offset + 1)}–{fa(Math.min(offset + PAGE, page.data.total))} از {fa(page.data.total)}</span>
            <div className="flex gap-2">
              <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}><ChevronRight className="h-3.5 w-3.5" /> قبلی</Button>
              <Button size="sm" disabled={offset + PAGE >= page.data.total} onClick={() => setOffset(offset + PAGE)}>بعدی <ChevronLeft className="h-3.5 w-3.5" /></Button>
            </div>
          </div>
        </>
      )}
    </>
  )
}

function DocRow({ d, onOpen }: { d: ArchiveDocument; onOpen: () => void }) {
  const meta = (d.metadata ?? d.doc_metadata ?? {}) as Record<string, unknown>
  return (
    <button onClick={onOpen} className="flex w-full items-start gap-4 px-5 py-3.5 text-start transition hover:bg-white/[.025]">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium text-white/85">{fa(d.title ?? d.source)}</div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-white/40">
          <span className="ltr">{d.source}</span>
          {meta.doc_kind ? <span>{String(meta.doc_kind)}</span> : null}
          {meta.court ? <span>{fa(String(meta.court))}</span> : null}
          {meta.date ? <span>{fa(String(meta.date))}</span> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {meta.status ? <Pill>{STATUS_FA[String(meta.status)] ?? String(meta.status)}</Pill> : null}
        <span className="tnum text-[11px] text-white/35">{fa(typeof d.chunks === 'number' ? d.chunks : d.chunks?.length ?? 0)} قطعه</span>
      </div>
    </button>
  )
}

function DocumentFile({ id }: { id: string }) {
  const doc = useQuery({ queryKey: ['document', id], queryFn: () => api.document(id) })
  const refresh = useRefreshArchive()
  const { closeInner } = useShell()
  const [tab, setTab] = useState<'text' | 'chunks'>('text')
  const [tag, setTag] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  usePublishContext('documents', { entityKind: 'document', entityLabel: doc.data?.title?.slice(0, 30) ?? undefined, documentIds: [id], view: tab === 'text' ? 'متن کامل' : 'قطعه‌ها' })
  const patch = useMutation({ mutationFn: (body: Parameters<typeof api.patchDocumentMeta>[1]) => api.patchDocumentMeta(id, body), onSuccess: () => { void doc.refetch(); void refresh() } })
  const remove = useMutation({
    mutationFn: () => api.deleteDocument(id),
    onSuccess: () => { useAssistant.getState().toast({ tone: 'info', title: 'سند حذف شد', detail: 'قطعه‌های آن هم حذف شدند.' }); useAssistant.getState().log({ kind: 'deleted', text: `سند «${doc.data?.title ?? id}» حذف شد`, refs: [id] }); void refresh(); closeInner(id) },
  })
  if (doc.error) return <LoadError error={doc.error} retry={() => void doc.refetch()} />
  if (!doc.data) return <Skeleton />
  const d = doc.data
  const meta = (d.doc_metadata ?? {}) as Record<string, unknown>
  const tags = (meta.tags as string[] | undefined) ?? []
  return (
    <>
      <PageHeader eyebrow={`سند · ${d.source}`} title={fa(d.title ?? d.source)} summary={`ثبت ${date(d.created_at)} · ${fa(d.chunks.length)} قطعه`} />
      <div className="mt-5 grid gap-5 xl:grid-cols-[1fr_340px]">
        <Card>
          <div className="px-5 pt-4"><Segmented layoutId={`doc-${id}`} value={tab} onChange={setTab} items={[{ id: 'text', label: 'متن کامل' }, { id: 'chunks', label: `قطعات (${fa(d.chunks.length)})` }]} /></div>
          {tab === 'text' ? <div className="whitespace-pre-wrap px-6 py-5 text-[14px] leading-8 text-white/80">{d.raw_text || '—'}</div> : (
            <ol className="space-y-2.5 px-5 py-5">{d.chunks.map((c) => <li key={c.chunk_index} className="rounded-2xl border border-white/[.06] bg-white/[.02] p-3"><div className="tnum mb-1 text-[11px] text-white/35">قطعهٔ {fa(c.chunk_index + 1)}</div><p className="whitespace-pre-wrap text-[12.5px] leading-7 text-white/70">{c.text}</p></li>)}</ol>
          )}
        </Card>
        <div className="space-y-5">
          <Card>
            <CardHeader title="تیکت" subtitle="وضعیت و برچسب‌های این سند" />
            <div className="space-y-3 px-5 pb-5">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(STATUS_FA).map(([k, v]) => <button key={k} disabled={patch.isPending} onClick={() => patch.mutate({ status: k })} className={`rounded-full border px-3 py-1 text-[11.5px] ${meta.status === k ? 'border-cyan-300/30 bg-cyan-300/10 text-cyan-100' : 'border-white/10 text-white/55 hover:text-white'}`}>{v}</button>)}
              </div>
              <Chips tone="teal" items={tags.map((t) => `${t} ×`)} onClick={(t) => patch.mutate({ remove_tags: [t.replace(' ×', '')] })} />
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (tag.trim()) { patch.mutate({ add_tags: [tag.trim()] }); setTag('') } }}>
                <input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="برچسب جدید…" className="h-9 flex-1 rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none" />
                <Button size="sm" type="submit"><Tag className="h-3.5 w-3.5" /> افزودن</Button>
              </form>
              {patch.error && <div className="text-[11.5px] text-rose-200/80">{describeError(patch.error)}</div>}
            </div>
          </Card>
          <Card className="px-5 py-3"><KV rows={Object.entries(meta).filter(([k, v]) => !['tags'].includes(k) && typeof v !== 'object').slice(0, 14).map(([k, v]) => [k, fa(String(v))])} /></Card>
          <Card className="p-5">
            {!confirmDelete ? <Button variant="danger" onClick={() => setConfirmDelete(true)}><Trash2 className="h-4 w-4" /> حذف این سند</Button> : (
              <div className="space-y-2">
                <div className="text-[12px] leading-6 text-rose-100/85">سند و همهٔ قطعه‌های آن حذف می‌شوند. این کار برگشت‌پذیر نیست.</div>
                <div className="flex gap-2"><Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>انصراف</Button><Button size="sm" variant="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>{remove.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />} تأیید حذف</Button></div>
                {remove.error && <div className="text-[11.5px] text-rose-200/80">{describeError(remove.error)}</div>}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  )
}
