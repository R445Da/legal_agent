import { useArchive } from '@/api/queries'
import { fa } from '@/lib/format'
import { usePublishContext } from '@/state/context'
import type { WorkspaceTab } from '@/state/shell'
import { Card, CardHeader, Pill } from '@/components/ui/misc'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'
import { PIPELINE } from '@/components/assistant/RunStepper'

const INTENT_FA: Record<string, string> = { query: 'پرسش از اسناد', archive: 'ثبت مطلب جدید', analytics: 'آمار آرشیو', law: 'پرسش از قوانین', cases: 'بایگانی پرونده‌ها', agent: 'پژوهش عاملی' }

/** ۱۲ ساختار داده و خط لوله — what the system stores and how, so it can explain itself. */
export function SchemaView({ ws }: { ws: WorkspaceTab }) {
  const { data, error } = useArchive()
  usePublishContext('schema', {})
  if (error) return <LoadError error={error} />
  if (!data) return <Skeleton />
  const s = data.schema
  return (
    <>
      <PageHeader eyebrow="۱۲ · ساختار داده و خط لوله" title={{ model: 'مدل داده', pipeline: 'خط لوله', form: 'فرم مدخل' }[ws.tab] ?? 'ساختار داده'} summary="آنچه سامانه ذخیره می‌کند و مسیری که هر پیام طی می‌کند." />
      {ws.tab === 'model' && (
        <div className="mt-6 grid gap-4 lg:grid-cols-3">
          {s.model.map((m) => (
            <Card key={m.name} className="p-5">
              <div className="flex items-baseline justify-between"><div className="text-[15px] font-semibold">{m.fa} <span className="ltr text-[11px] text-white/35">{m.name}</span></div><Pill>{fa(m.count)}</Pill></div>
              <p className="mt-2 text-[12.5px] leading-6 text-white/55">{m.what}</p>
              <ul className="mt-3 space-y-1">{m.fields.map((f) => <li key={f} className="rounded-lg bg-white/[.03] px-2.5 py-1 text-[11.5px] text-white/65">{f}</li>)}</ul>
            </Card>
          ))}
        </div>
      )}
      {ws.tab === 'pipeline' && (
        <div className="mt-6 space-y-4">
          {Object.entries(s.pipeline).map(([intent, steps]) => (
            <Card key={intent} className="p-5">
              <div className="mb-3 text-sm font-medium">{INTENT_FA[intent] ?? intent}</div>
              <ol className="flex flex-wrap items-center gap-2">{steps.map((st, i) => <li key={i} className="flex items-center gap-2"><span className={`rounded-xl border px-3 py-1.5 text-[12px] ${st.includes('✋') ? 'border-amber-300/25 bg-amber-300/[.06] text-amber-100' : 'border-white/[.08] bg-white/[.03] text-white/70'}`}>{st}</span>{i < steps.length - 1 && <span className="text-white/20">←</span>}</li>)}</ol>
            </Card>
          ))}
          <Card className="p-5">
            <div className="mb-3 text-sm font-medium">گام‌های خط لولهٔ ثبت (نسخهٔ بیمه)</div>
            <ol className="flex flex-wrap items-center gap-2">{PIPELINE.map((p, i) => <li key={p.id} className="flex items-center gap-2"><span className="rounded-xl border border-violet-300/20 bg-violet-300/[.06] px-3 py-1.5 text-[12px] text-violet-100">{fa(i + 1)}. {p.label}</span>{i < PIPELINE.length - 1 && <span className="text-white/20">←</span>}</li>)}</ol>
          </Card>
          <p className="text-[12px] text-white/45">{s.pipeline_note}</p>
        </div>
      )}
      {ws.tab === 'form' && (
        <Card className="mt-6">
          <CardHeader title={s.entry_form.title} />
          <div className="divide-y divide-white/[.05]">
            {s.entry_form.fields.map((f) => (
              <div key={f.key} className="grid gap-2 px-5 py-3 sm:grid-cols-[200px_120px_1fr]">
                <div className="text-[13px] text-white/85">{f.label} <span className="ltr block text-[10.5px] text-white/30">{f.key}</span></div>
                <div><Pill>{f.type}</Pill></div>
                <div className="text-[12px] leading-6 text-white/50">{f.help}{f.options && <span className="block text-white/35">گزینه‌ها: {f.options.join('، ')}</span>}{f.roles && <span className="block text-white/35">نقش‌ها: {Object.values(f.roles).join('، ')}</span>}</div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}
