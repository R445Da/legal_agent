import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Plus, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import { ago, fa } from '@/lib/format'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import type { WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, Empty, Pill } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

type Hook = { id: string; url: string; events: string[]; active: boolean; description: string | null; created_at: string | null; secret?: string }
type Delivery = { id: string; event: string; status: string; attempts: number; response_code: number | null; error: string | null; created_at: string | null; sent_at: string | null }
const STATUS_TONE: Record<string, 'good' | 'warn' | 'bad' | 'neutral'> = { sent: 'good', pending: 'warn', failed: 'bad', dead: 'bad' }
const STATUS_FA: Record<string, string> = { sent: 'ارسال‌شده', pending: 'در صف', failed: 'ناموفق', dead: 'متوقف' }

/** ۱۹ وب‌هوک‌ها و CI — signed outbound webhooks, their deliveries, and inbound CI events. */
export function WebhooksView({ ws }: { ws: WorkspaceTab }) {
  usePublishContext('webhooks', {})
  return (
    <>
      <PageHeader eyebrow="۱۹ · وب‌هوک‌ها و CI" title={{ hooks: 'اشتراک‌ها', deliveries: 'تحویل‌ها', ci: 'خط لولهٔ CI' }[ws.tab] ?? 'وب‌هوک‌ها'} summary="هر تحویل با X-Legal-Signature-256 (HMAC) امضا می‌شود؛ رویدادهای CI از GitHub یا scripts/ci_status.sh می‌رسند." />
      {ws.tab === 'deliveries' ? <Deliveries /> : ws.tab === 'ci' ? <Ci /> : <Hooks />}
    </>
  )
}

function Hooks() {
  const qc = useQueryClient()
  const hooks = useQuery({ queryKey: ['hooks'], queryFn: api.hooks })
  const [f, setF] = useState({ url: '', description: '', events: [] as string[] })
  const [secret, setSecret] = useState<string | null>(null)
  const create = useMutation({ mutationFn: () => api.addHook({ url: f.url, events: f.events, description: f.description || undefined }), onSuccess: (h) => { setSecret(String((h as Hook).secret ?? '')); setF({ url: '', description: '', events: [] }); void qc.invalidateQueries({ queryKey: ['hooks'] }); useAssistant.getState().log({ kind: 'saved', text: `اشتراک وب‌هوک برای ${f.url} ساخته شد`, refs: [] }) } })
  const remove = useMutation({ mutationFn: api.deleteHook, onSuccess: () => void qc.invalidateQueries({ queryKey: ['hooks'] }) })
  const test = useMutation({ mutationFn: api.testHook, onSuccess: (d) => useAssistant.getState().toast({ tone: (d as Delivery).status === 'sent' ? 'success' : 'error', title: `ping: ${STATUS_FA[(d as Delivery).status] ?? (d as Delivery).status}`, detail: (d as Delivery).error ?? (d as Delivery).response_code?.toString() }) })
  if (hooks.error) return <LoadError error={hooks.error} />
  if (!hooks.data) return <Skeleton />
  const list = hooks.data.hooks as Hook[]
  return (
    <div className="mt-6 grid gap-5 xl:grid-cols-[1fr_400px]">
      <Card className="divide-y divide-white/[.05] self-start">
        {list.map((h) => (
          <div key={h.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
            <div className="min-w-0 flex-1"><div className="ltr truncate text-start font-mono text-[12px] text-white/80">{h.url}</div><div className="mt-0.5 text-[11px] text-white/40">{h.description ?? '—'} · {h.events.join('، ') || 'همهٔ رویدادها'}</div></div>
            <Pill tone={h.active ? 'good' : 'neutral'} dot>{h.active ? 'فعال' : 'غیرفعال'}</Pill>
            <Button size="sm" onClick={() => test.mutate(h.id)} disabled={test.isPending}><Send className="h-3.5 w-3.5 -scale-x-100" /> ping</Button>
            <Button size="sm" variant="danger" onClick={() => remove.mutate(h.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
          </div>
        ))}
        {!list.length && <Empty title="اشتراکی ثبت نشده" detail="یک نشانی بسازید تا رویدادهای ثبت مدخل و پاسخ‌ها به آن برسد." />}
      </Card>
      <Card className="self-start p-5">
        <div className="text-sm font-medium">اشتراک جدید</div>
        <label className="mt-3 block text-[11.5px] text-white/45">نشانی<input className="ltr mt-1 h-10 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 font-mono text-xs outline-none" placeholder="https://example.com/hook" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></label>
        <label className="mt-2 block text-[11.5px] text-white/45">توضیح<input className="mt-1 h-10 w-full rounded-xl border border-white/10 bg-white/[.04] px-3 text-xs outline-none" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <div className="mt-3 flex flex-wrap gap-1.5">{hooks.data.events.map((ev) => { const on = f.events.includes(ev); return <button key={ev} onClick={() => setF({ ...f, events: on ? f.events.filter((x) => x !== ev) : [...f.events, ev] })} className={`ltr rounded-full border px-2.5 py-0.5 font-mono text-[11px] ${on ? 'border-cyan-300/40 bg-cyan-300/15 text-cyan-50' : 'border-white/10 text-white/50'}`}>{ev}</button> })}</div>
        <p className="mt-2 text-[10.5px] text-white/30">بدون انتخاب = همهٔ رویدادها.</p>
        {create.error && <div className="mt-2 text-[12px] text-rose-200/80">{describeError(create.error)}</div>}
        <Button className="mt-3" variant="primary" disabled={!f.url.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} ساخت اشتراک</Button>
        {secret && <div className="mt-3 rounded-2xl border border-amber-300/20 bg-amber-300/[.06] p-3 text-[12px] text-amber-50/90"><CheckCircle2 className="me-1 inline h-3.5 w-3.5" /> رمز امضا — فقط همین یک‌بار نمایش داده می‌شود:<div className="ltr mt-1 select-all break-all font-mono text-[11px]">{secret}</div></div>}
      </Card>
    </div>
  )
}

function Deliveries() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['deliveries'], queryFn: api.deliveries, refetchInterval: 5000 })
  const drain = useMutation({ mutationFn: api.drainHooks, onSuccess: (r) => { useAssistant.getState().toast({ tone: 'info', title: `${fa(r.tried)} تحویل تلاش شد` }); void qc.invalidateQueries({ queryKey: ['deliveries'] }) } })
  if (list.error) return <LoadError error={list.error} />
  if (!list.data) return <Skeleton />
  const rows = list.data.deliveries as Delivery[]
  return (
    <Card className="mt-6">
      <CardHeader title="تحویل‌ها" subtitle="هر پنج ثانیه به‌روز می‌شود" right={<Button size="sm" disabled={drain.isPending} onClick={() => drain.mutate()}>{drain.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />} ارسال موارد در صف</Button>} />
      <div className="divide-y divide-white/[.05]">
        {rows.map((d) => (
          <div key={d.id} className="flex flex-wrap items-center gap-3 px-5 py-2.5 text-[12.5px]">
            <span className="ltr font-mono text-[11.5px] text-white/75">{d.event}</span>
            <Pill tone={STATUS_TONE[d.status] ?? 'neutral'}>{STATUS_FA[d.status] ?? d.status}</Pill>
            <span className="text-[11px] text-white/40">{fa(d.attempts)} تلاش{d.response_code ? ` · ${fa(d.response_code)}` : ''}</span>
            {d.error && <span className="min-w-0 flex-1 truncate text-[11px] text-rose-200/70">{d.error}</span>}
            <span className="ms-auto text-[11px] text-white/30">{d.created_at ? ago(d.created_at) : ''}</span>
          </div>
        ))}
        {!rows.length && <Empty title="تحویلی ثبت نشده" />}
      </div>
    </Card>
  )
}

function Ci() {
  const ci = useQuery({ queryKey: ['ci-events'], queryFn: api.ciEvents, refetchInterval: 3000 })
  if (ci.error) return <LoadError error={ci.error} />
  if (!ci.data) return <Skeleton />
  const runs = ci.data.runs as { id?: string; title?: string; name?: string; branch?: string; status?: string; conclusion?: string; jobs?: { name: string; status?: string; conclusion?: string; stages?: { name: string; status?: string; conclusion?: string }[] }[] }[]
  return (
    <div className="mt-6 space-y-4">
      {runs.map((r, i) => (
        <Card key={r.id ?? i} className="p-5">
          <div className="flex items-center justify-between gap-3"><div><div className="text-[14px] font-medium">{r.title ?? r.name ?? r.id}</div><div className="ltr text-start font-mono text-[11px] text-white/35">{r.branch}</div></div><Pill tone={r.conclusion === 'success' ? 'good' : r.conclusion === 'failure' ? 'bad' : 'info'} dot>{r.conclusion ?? r.status}</Pill></div>
          <div className="mt-3 grid gap-2 md:grid-cols-3">{(r.jobs ?? []).map((j) => (
            <div key={j.name} className="rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
              <div className="flex justify-between text-[12px]"><span className="ltr font-mono">{j.name}</span><Pill tone={j.conclusion === 'success' ? 'good' : j.conclusion === 'failure' ? 'bad' : 'info'}>{j.conclusion ?? j.status}</Pill></div>
              <ul className="mt-2 space-y-1">{(j.stages ?? []).map((s) => <li key={s.name} className="flex justify-between text-[11px] text-white/50"><span className="ltr font-mono">{s.name}</span><span>{s.conclusion ?? s.status}</span></li>)}</ul>
            </div>
          ))}</div>
        </Card>
      ))}
      {!runs.length && <Card><Empty title="رویدادی از CI نرسیده است" detail="«python -m scripts.replay_ci» یک اجرا را بازپخش می‌کند؛ یا CI_STATUS_URL را در مخزن تنظیم کنید." /></Card>}
    </div>
  )
}
