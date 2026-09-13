import { useMemo } from 'react'
import { useArchive } from '@/api/queries'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Card, CardHeader, Empty, Pill } from '@/components/ui/misc'
import { Bar } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'
import { CaseRow } from './cases'

/** ۰۸ طبقه‌بندی و برچسب‌ها — the taxonomy tree and what each tag covers. */
export function TaxonomyView({ ws }: { ws: WorkspaceTab }) {
  const { data, error, refetch } = useArchive()
  const { setQuery, open } = useShell()
  const tag = ws.query ?? ''
  usePublishContext('taxonomy', { filters: tag ? { برچسب: tag } : undefined })
  const counts = useMemo(() => new Map((data?.tags ?? []).map((t) => [t.tag, t.cases])), [data])
  if (error) return <LoadError error={error} retry={() => void refetch()} />
  if (!data) return <Skeleton />
  const max = Math.max(...data.tags.map((t) => t.cases), 1)
  const cases = tag ? data.cases.filter((c) => c.tags.includes(tag)) : []
  return (
    <>
      <PageHeader eyebrow="۰۸ · طبقه‌بندی و برچسب‌ها" title="طبقه‌بندی و برچسب‌ها" summary="برچسب‌ها از استخراج ساختاریافته و خط لولهٔ ثبت می‌آیند. روی هر برچسب بزنید تا پرونده‌های آن را ببینید." right={<Pill>{fa(data.tags.length)} برچسب</Pill>} />
      <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_420px]">
        <div className="space-y-5">
          <Card>
            <CardHeader title="درخت طبقه‌بندی" subtitle="برگ‌ها پیشنهادهای گام «برچسب‌ها» در خط لوله‌اند" />
            <div className="grid gap-4 px-5 pb-5 md:grid-cols-2">
              {data.taxonomy.map((root) => (
                <div key={root.root} className="rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
                  <div className="text-[13px] font-semibold">{root.root}</div>
                  {root.categories.map((cat) => (
                    <div key={cat.name} className="mt-2">
                      <div className="text-[11.5px] text-white/45">{cat.name}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">{cat.leaves.map((leaf) => (
                        <button key={leaf} onClick={() => setQuery(leaf)} className={cn('rounded-full border px-2.5 py-0.5 text-[11.5px]', leaf === tag ? 'border-cyan-300/40 bg-cyan-300/15 text-cyan-50' : counts.get(leaf) ? 'border-cyan-300/15 bg-cyan-300/[.06] text-cyan-100/85' : 'border-white/[.07] text-white/40')}>{leaf}{counts.get(leaf) ? ` · ${fa(counts.get(leaf)!)}` : ''}</button>
                      ))}</div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="برچسب‌های آرشیو" subtitle="بر اساس تعداد پرونده" />
            <ul className="grid gap-x-6 gap-y-2.5 px-5 pb-5 md:grid-cols-2">
              {data.tags.map((t) => (
                <li key={t.tag}><button onClick={() => setQuery(t.tag)} className="w-full text-start"><div className="mb-1 flex justify-between text-[12px]"><span className={cn('truncate', t.tag === tag ? 'text-cyan-100' : 'text-white/70')}>{t.tag}</span><span className="tnum text-white/40">{fa(t.cases)}</span></div><Bar value={t.cases} max={max} /></button></li>
              ))}
            </ul>
          </Card>
        </div>
        <Card className="self-start">
          <CardHeader title={tag ? `پرونده‌های «${tag}»` : 'یک برچسب انتخاب کنید'} subtitle={tag ? `${fa(cases.length)} پرونده` : undefined} right={tag ? <button onClick={() => setQuery('')} className="text-[11px] text-white/45 hover:text-white">پاک کردن</button> : undefined} />
          <div className="space-y-2 px-5 pb-5">
            {cases.slice(0, 30).map((c) => <CaseRow key={c.id} c={c} onOpen={() => open('cases', { record: c.id, label: fa(c.number || c.title.slice(0, 16)) })} />)}
            {tag && !cases.length && <Empty title="پرونده‌ای با این برچسب نیست" />}
            {!tag && <div className="text-xs text-white/35">روی برچسبی در درخت یا فهرست بزنید.</div>}
          </div>
        </Card>
      </div>
    </>
  )
}
