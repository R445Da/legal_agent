import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, GitBranch } from 'lucide-react'
import { api } from '@/api/endpoints'
import { useArchive } from '@/api/queries'
import { compactRial, fa } from '@/lib/format'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Card, CardHeader, Pill, Stat } from '@/components/ui/misc'
import { Bar, CaseNo, Chips, Timeline } from '@/components/shared/Bits'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/** ۰۲ داشبورد — the state of the archive at a glance. */
export function DashboardView(_: { ws: WorkspaceTab }) {
  const { data, error, refetch } = useArchive()
  const open = useShell((s) => s.open)
  const live = useQuery({ queryKey: ['integrations'], queryFn: api.integrations, refetchInterval: 3000, retry: false })
  usePublishContext('dashboard', {})
  if (error) return <LoadError error={error} retry={() => void refetch()} />
  if (!data) return <Skeleton />
  const a = data.archive
  const maxType = Math.max(...a.by_type.map((t) => t.count), 1)
  return (
    <>
      <PageHeader eyebrow="۰۲ · داشبورد" title="وضعیت آرشیو در یک نگاه" summary="بایگانی پرونده‌های بیمه‌ای، پایگاه قوانین و آنچه دستیار در آن نمایه کرده است." />
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="پرونده‌ها (بایگانی)" value={fa(a.cases)} hint={`مجموع خواسته ${compactRial(a.claim_total)}`} />
        <Stat label="مواد قانونی" value={fa(a.laws)} hint={`${fa(a.citations)} استناد`} />
        <Stat label="اشخاص و سازمان‌ها" value={fa(a.persons + a.orgs)} hint={`${fa(a.persons)} شخص · ${fa(a.orgs)} سازمان`} />
        <Stat label="میانگین خواسته" value={compactRial(a.claim_avg)} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="پرونده‌ها (مدخل‌ها)" value={fa(data.cases.length)} />
        <Stat label="مدخل‌های ساختاریافته" value={fa(data.counts.entries)} />
        <Stat label="اسناد خام" value={fa(data.counts.documents)} />
        <Stat label="قطعات نمایه‌شده" value={fa(data.counts.chunks)} />
        <Stat label="در صف بازبینی" value={fa(data.review_queue.length)} tone={data.review_queue.length ? 'bad' : 'good'} />
      </div>

      <Card className="mt-5">
        <CardHeader title={<span className="flex items-center gap-2"><GitBranch className="h-4 w-4 text-white/45" /> خط لولهٔ CI و وب‌هوک‌ها</span>} subtitle="هر سه ثانیه به‌روز می‌شود" right={<Pill tone={live.error ? 'neutral' : 'good'} dot>{live.error ? 'در دسترس نیست' : 'زنده'}</Pill>} />
        <div className="px-5 pb-4 text-[12.5px]">
          {live.error ? <div className="text-white/40">جدول‌های v3 در این پایگاه‌داده نیستند.</div> : (
            <div className="space-y-2">
              {((live.data?.ci_runs ?? []) as { id?: string; title?: string; name?: string; conclusion?: string; status?: string }[]).slice(0, 3).map((r, i) => (
                <div key={r.id ?? i} className="flex items-center justify-between rounded-xl border border-white/[.05] px-3 py-2"><span className="text-white/75">{r.title ?? r.name ?? r.id}</span><Pill tone={r.conclusion === 'success' ? 'good' : r.conclusion === 'failure' ? 'bad' : 'info'}>{r.conclusion ?? r.status}</Pill></div>
              ))}
              {!(live.data?.ci_runs ?? []).length && <div className="text-white/40">هنوز رویدادی از CI نرسیده است — «python -m scripts.replay_ci» یک اجرا را بازپخش می‌کند.</div>}
              <div className="text-[11.5px] text-white/40">وب‌هوک‌ها: {fa(live.data?.hooks.subscriptions ?? 0)} اشتراک{Object.entries(live.data?.hooks ?? {}).filter(([k]) => k !== 'subscriptions').map(([k, v]) => ` · ${fa(v)} ${({ sent: 'ارسال‌شده', pending: 'در صف', failed: 'ناموفق', dead: 'متوقف' } as Record<string, string>)[k] ?? k}`).join('')}</div>
            </div>
          )}
        </div>
      </Card>

      <div className="mt-5 grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="آخرین رویدادها" right={<button onClick={() => open('events')} className="text-[11px] text-white/45 hover:text-white">همهٔ رویدادها</button>} />
          <div className="px-5 pb-5">
            <Timeline items={data.events.slice(0, 8).map((e) => ({ date: e.date, title: fa(e.description ?? e.what ?? e.type ?? '—'), detail: fa(e.case_title), onClick: () => open('cases', { record: e.case_id, label: fa(e.case_number || '') }) }))} />
          </div>
        </Card>
        <div className="space-y-5">
          <Card>
            <CardHeader title="پرونده‌ها بر اساس نوع دعوا" />
            <ul className="space-y-2.5 px-5 pb-5">
              {a.by_type.slice(0, 8).map((t) => (
                <li key={t.name}>
                  <button onClick={() => open('cases', { tab: 'all', query: t.name })} className="w-full text-start">
                    <div className="mb-1 flex justify-between gap-3 text-[12px]"><span className="truncate text-white/75">{t.name}</span><span className="tnum text-white/45">{fa(t.count)}</span></div>
                    <Bar value={t.count} max={maxType} />
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title={<span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-rose-300/80" /> صف بازبینی</span>} right={<button onClick={() => open('review')} className="text-[11px] text-white/45 hover:text-white">باز کردن</button>} />
            <div className="space-y-2 px-5 pb-5">
              {data.review_queue.slice(0, 4).map((c) => (
                <button key={c.id} onClick={() => open('review')} className="block w-full rounded-xl border border-white/[.05] px-3 py-2 text-start text-[12.5px] hover:bg-white/[.03]">
                  <div className="text-white/80">{fa(c.title)}</div>
                  <div className="text-[11px] text-rose-200/60">{c.incomplete_reasons.join('، ')}</div>
                </button>
              ))}
              {!data.review_queue.length && <div className="text-[12.5px] text-white/40">صف خالی است — همهٔ پرونده‌ها کامل‌اند.</div>}
            </div>
          </Card>
          <Card>
            <CardHeader title="برچسب‌های پرتکرار" />
            <div className="px-5 pb-5"><Chips tone="teal" items={data.tags.slice(0, 16).map((t) => `${t.tag} · ${fa(t.cases)}`)} onClick={(t) => open('taxonomy', { query: t.split(' · ')[0] })} /></div>
          </Card>
        </div>
      </div>
      <div className="mt-5 text-[11px] text-white/25">آخرین پرونده: <CaseNo value={data.cases[0]?.number} /></div>
    </>
  )
}
