import { useQuery } from '@tanstack/react-query'
import { FolderOpen, Search } from 'lucide-react'
import { api } from '@/api/endpoints'
import type { LegalCaseRecord } from '@/api/types'
import { compactRial, fa } from '@/lib/format'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Card, CardHeader, Empty, Pill, Stat } from '@/components/ui/misc'
import { Bar } from '@/components/shared/Bits'
import { GraphView } from '@/components/shared/GraphView'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

type Kind = 'person' | 'org'
const KIND_FA: Record<Kind, string> = { person: 'شخص', org: 'سازمان' }

/** ۱۶ اشخاص و سازمان‌ها — every name is a record: its cases, roles, counterparties and graph. */
export function EntitiesView({ ws }: { ws: WorkspaceTab }) {
  const kind = (ws.tab === 'org' ? 'org' : 'person') as Kind
  if (ws.active) return <Profile kind={kind} id={ws.active} />
  return <List kind={kind} query={ws.query ?? ''} />
}

function List({ kind, query }: { kind: Kind; query: string }) {
  const { setQuery, openInner } = useShell()
  const list = useQuery({ queryKey: ['entities', kind, query], queryFn: () => api.entities(kind, query || undefined) })
  usePublishContext('entities', { filters: query ? { جستجو: query } : undefined })
  const max = Math.max(...(list.data?.items ?? []).map((e) => e.cases), 1)
  return (
    <>
      <PageHeader eyebrow="۱۶ · اشخاص و سازمان‌ها" title={kind === 'person' ? 'اشخاص' : 'سازمان‌ها'} summary="نام‌ها با حذف عنوان‌ها (آقای، خانم، دکتر…) یکی می‌شوند. روی هر ردیف بزنید تا پروفایل و گراف ارتباطات باز شود." right={list.data && <Pill>{fa(list.data.items.length)} {KIND_FA[kind]}</Pill>} />
      <div className="glass mt-5 flex items-center gap-2 rounded-2xl px-3"><Search className="h-4 w-4 text-white/35" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`جستجوی ${KIND_FA[kind]}…`} className="h-10 flex-1 bg-transparent text-[13px] outline-none" /></div>
      {list.error ? <LoadError error={list.error} /> : !list.data ? <Skeleton /> : (
        <Card className="mt-4 divide-y divide-white/[.05]">
          {list.data.items.map((e) => (
            <button key={e.id} onClick={() => openInner(e.id, e.name.slice(0, 22))} className="flex w-full items-center gap-4 px-5 py-3 text-start transition hover:bg-white/[.025]">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-white/85">{e.name}</div>
                <div className="text-[11px] text-white/40">{e.roles_fa.join('، ') || '—'}{e.kind ? ` · ${e.kind}` : ''}</div>
              </div>
              <div className="w-32"><Bar value={e.cases} max={max} tone="violet" /></div>
              <div className="tnum w-16 text-end text-[12px] text-white/55">{fa(e.cases)} پرونده</div>
            </button>
          ))}
          {!list.data.items.length && <Empty title="موردی یافت نشد" />}
        </Card>
      )}
    </>
  )
}

interface Profile { id: string; name: string; roles_fa: string[]; kind: string | null; cases: LegalCaseRecord[]; case_count: number; represents: { name: string; count: number }[]; represented_by: { name: string; count: number }[]; by_line: { name: string; count: number }[]; by_type: { name: string; count: number }[]; by_outcome: { name: string; count: number }[] }

function Profile({ kind, id }: { kind: Kind; id: string }) {
  const { open, openInner } = useShell()
  const prof = useQuery({ queryKey: ['entity', kind, id], queryFn: () => api.entity(kind, id) as Promise<unknown> as Promise<Profile> })
  const graph = useQuery({ queryKey: ['entity-graph', kind, prof.data?.id], queryFn: () => api.graph(kind, prof.data!.id), enabled: !!prof.data })
  usePublishContext('entities', { entityKind: kind, entityLabel: prof.data?.name, view: 'پروفایل' })
  if (prof.error) return <LoadError error={prof.error} retry={() => void prof.refetch()} />
  if (!prof.data) return <Skeleton />
  const p = prof.data
  const Breakdown = ({ title, rows }: { title: string; rows: { name: string; count: number }[] }) => (
    <Card><CardHeader title={title} /><ul className="space-y-2 px-5 pb-5">{rows.slice(0, 6).map((r) => <li key={r.name}><div className="mb-1 flex justify-between text-[12px]"><span className="truncate text-white/70">{fa(r.name)}</span><span className="tnum text-white/40">{fa(r.count)}</span></div><Bar value={r.count} max={Math.max(...rows.map((x) => x.count), 1)} tone="violet" /></li>)}{!rows.length && <li className="text-xs text-white/35">—</li>}</ul></Card>
  )
  return (
    <>
      <PageHeader eyebrow={`${KIND_FA[kind]}${p.kind ? ` · ${p.kind}` : ''}`} title={p.name} summary={p.roles_fa.join('، ')} />
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Stat label="پرونده‌ها" value={fa(p.case_count)} />
        <Stat label="وکیلِ" value={fa(p.represents?.length ?? 0)} hint="موکل" />
        <Stat label="با وکالتِ" value={fa(p.represented_by?.length ?? 0)} hint="وکیل" />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader title="پرونده‌ها" />
          <div className="space-y-2 px-5 pb-5">
            {p.cases.map((c) => (
              <button key={c.id} onClick={() => open('cases', { record: c.case_number, label: fa(c.case_number) })} className="block w-full rounded-2xl border border-white/[.06] bg-white/[.02] p-3 text-start hover:bg-white/[.04]">
                <div className="flex items-center gap-2 text-[12.5px] text-white/85"><FolderOpen className="h-3.5 w-3.5 text-cyan-200/60" /> {fa(c.title)}</div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-white/40">{c.case_type && <span>{c.case_type}</span>}{c.status_fa && <span>{c.status_fa}</span>}{c.claim_amount ? <span>{compactRial(c.claim_amount)}</span> : null}</div>
                {c.outcome && <div className="mt-0.5 line-clamp-1 text-[11px] text-white/50">نتیجه: {fa(c.outcome)}</div>}
              </button>
            ))}
          </div>
        </Card>
        <div className="space-y-5">
          {(p.represents?.length || p.represented_by?.length) ? (
            <Card>
              <CardHeader title="وکالت" />
              <div className="space-y-3 px-5 pb-5 text-[12.5px]">
                {p.represents?.length ? <div><div className="mb-1 text-[11px] text-white/40">وکیلِ</div>{p.represents.map((r) => <button key={r.name} onClick={() => openInner(r.name, r.name.slice(0, 22))} className="flex w-full justify-between py-1 text-white/75 hover:text-white"><span>{r.name}</span><span className="tnum text-white/40">{fa(r.count)}</span></button>)}</div> : null}
                {p.represented_by?.length ? <div><div className="mb-1 text-[11px] text-white/40">با وکالتِ</div>{p.represented_by.map((r) => <button key={r.name} onClick={() => openInner(r.name, r.name.slice(0, 22))} className="flex w-full justify-between py-1 text-white/75 hover:text-white"><span>{r.name}</span><span className="tnum text-white/40">{fa(r.count)}</span></button>)}</div> : null}
              </div>
            </Card>
          ) : null}
          <Breakdown title="بر اساس رشتهٔ بیمه" rows={p.by_line ?? []} />
          <Breakdown title="بر اساس نوع دعوا" rows={p.by_type ?? []} />
          <Breakdown title="بر اساس نتیجه" rows={p.by_outcome ?? []} />
        </div>
      </div>
      <Card className="mt-5">
        <CardHeader title="گراف ارتباطات" />
        <div className="px-5 pb-5">{graph.data ? <GraphView graph={graph.data} focus={p.id} onNode={(n) => { if (n.type === 'case') open('cases', { record: String((n as Record<string, unknown>).case_number ?? n.id) }); else if (n.type === 'law') open('laws', { record: n.id }); else if (n.type === 'person' || n.type === 'org') open('entities', { tab: n.type, record: n.id, label: String(n.label).slice(0, 22) }) }} /> : graph.error ? <LoadError error={graph.error} /> : <Skeleton />}</div>
      </Card>
    </>
  )
}
