import { ChevronDown, FolderOpen, Scale, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import type { AnswerResult } from '@/api/types'
import { compactRial, fa, ms } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useShell } from '@/state/shell'
import { Citations } from '@/components/shared/Citations'
import { Lessons } from '@/components/shared/Lessons'
import { Markdown } from '@/components/shared/Markdown'
import { Pill } from '@/components/ui/misc'

/**
 * The evidence around an answer, by intent: cited excerpts (query), cited
 * articles and similar past cases (law / cases), the aggregates (analytics),
 * and the evidence ledger («شواهد و ردپای پاسخ») the engine persists.
 */
export function AnswerCard({ result, scope }: { result: AnswerResult; scope?: string }) {
  const open = useShell((s) => s.open)
  const stats = result.stats as Record<string, unknown> | undefined
  return (
    <div className="space-y-2.5">
      {scope && <Pill tone="info">{scope}</Pill>}

      {result.refs && result.refs.length > 0 && (
        <div className="space-y-1.5">
          {result.refs.slice(0, 8).map((r, i) => (
            <button key={r.id} onClick={() => open('laws', { record: r.id, label: `مادهٔ ${fa(r.article_no ?? '')}`, origin: 'tab' })}
              className="block w-full rounded-2xl border border-amber-300/10 bg-amber-300/[.04] px-3 py-2 text-start transition hover:bg-amber-300/[.07]">
              <div className="flex items-center gap-2 text-[11.5px]"><span className="tnum rounded-md bg-amber-300/15 px-1.5 text-amber-100">[{fa(i + 1)}]</span><Scale className="h-3.5 w-3.5 text-amber-200/70" /><span className="text-white/80">{fa(r.cite)}</span></div>
              {r.title && <div className="mt-0.5 text-[11px] text-white/50">{r.title}</div>}
              <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-white/40">{r.text}</p>
            </button>
          ))}
        </div>
      )}

      {result.cases && result.cases.length > 0 && <CaseRows title="پرونده‌های یافت‌شده" items={result.cases} numbered />}
      {result.similar_cases && result.similar_cases.length > 0 && <CaseRows title="پرونده‌های مشابه از گراف" items={result.similar_cases} />}

      {result.advice && (
        <div className="suggested rounded-2xl p-3 text-[12.5px] leading-7 text-violet-50/90">
          <div className="mb-1 text-[11px] text-violet-200/70">تحلیل تطبیقی دستیار — پیشنهاد، نه پیش‌بینی نتیجه</div>
          <Markdown text={result.advice} />
        </div>
      )}
      {result.lessons ? <Lessons lessons={result.lessons} /> : null}

      {stats && (
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {(['documents', 'entries', 'chunks', 'cases'] as const).filter((k) => typeof stats[k] === 'number').map((k) => (
            <div key={k} className="rounded-2xl border border-white/[.06] bg-white/[.03] px-3 py-2">
              <div className="text-[10.5px] text-white/35">{{ documents: 'اسناد', entries: 'مدخل‌ها', chunks: 'قطعه‌ها', cases: 'پرونده‌ها' }[k]}</div>
              <div className="tnum text-sm font-medium text-white/85">{fa(stats[k] as number)}</div>
            </div>
          ))}
        </div>
      )}

      {result.contexts && result.contexts.length > 0 && <Citations contexts={result.contexts} />}
      {result.provenance && <Provenance result={result} />}
      {result.steps && result.steps.length > 0 && <Steps result={result} />}
    </div>
  )
}

function CaseRows({ title, items, numbered }: { title: string; items: AnswerResult['cases']; numbered?: boolean }) {
  const open = useShell((s) => s.open)
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] text-white/40">{title}</div>
      {items!.slice(0, 6).map((c, i) => (
        <button key={c.id} onClick={() => open('cases', { record: c.case_number, label: fa(c.case_number), origin: 'tab' })}
          className="block w-full rounded-2xl border border-white/[.06] bg-white/[.025] px-3 py-2 text-start transition hover:bg-white/[.05]">
          <div className="flex items-center gap-2 text-[11.5px]">
            {numbered && <span className="tnum rounded-md bg-cyan-400/15 px-1.5 text-cyan-100">[{fa(i + 1)}]</span>}
            <FolderOpen className="h-3.5 w-3.5 text-cyan-200/60" />
            <span className="min-w-0 truncate text-white/80">{fa(c.title)}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-[10.5px] text-white/40">
            {c.case_type && <span>{c.case_type}</span>}{c.insurance_line && <span>{c.insurance_line}</span>}{c.status_fa && <span>{c.status_fa}</span>}{c.claim_amount ? <span>{compactRial(c.claim_amount)}</span> : null}
          </div>
          {c.outcome && <div className="mt-0.5 line-clamp-1 text-[11px] text-white/50">نتیجه: {fa(c.outcome)}</div>}
        </button>
      ))}
    </div>
  )
}

function Provenance({ result }: { result: AnswerResult }) {
  const [open, setOpen] = useState(false)
  const p = result.provenance!
  return (
    <div className="rounded-2xl border border-emerald-300/10 bg-emerald-300/[.03]">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-3 py-2 text-[11.5px] text-emerald-100/70 hover:text-emerald-50">
        <span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> شواهد و ردپای پاسخ · {fa(p.evidence.length)} منبع</span>
        <ChevronDown className={cn('h-4 w-4 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="space-y-1 px-3 pb-3 text-[11px]">
          {p.evidence.map((e) => <div key={`${e.kind}-${e.n}`} className="flex gap-2 text-white/60"><span className="tnum text-emerald-200/70">[{fa(e.n)}]</span><span>{fa(e.label ?? e.cite ?? e.title ?? '')}</span></div>)}
          <div className="pt-1 text-[10.5px] text-white/30">مدل: <span className="ltr">{p.model}</span>{result.answer_id ? ` · شناسهٔ پاسخ ${result.answer_id.slice(0, 8)}` : ''}</div>
        </div>
      )}
    </div>
  )
}

function Steps({ result }: { result: AnswerResult }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)} className="text-[11px] text-white/35 hover:text-white/70">
        مراحل اجرا ({fa(result.steps!.length)}){result.latency_ms ? ` · ${ms(result.latency_ms)}` : ''} {open ? '▴' : '▾'}
      </button>
      {open && (
        <ol className="mt-1.5 space-y-1 border-s border-white/[.08] ps-3">
          {result.steps!.map((s, i) => (
            <li key={i} className="text-[11px] leading-5 text-white/50"><span className="text-white/75">{s.name}</span>{s.detail ? ` — ${fa(s.detail)}` : ''}{s.ms ? <span className="text-white/30"> · {ms(s.ms)}</span> : null}</li>
          ))}
        </ol>
      )}
    </div>
  )
}
