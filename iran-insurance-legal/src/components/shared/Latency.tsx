import { ms } from '@/lib/format'

/** Where the wall clock went — vector, lexical, rerank, generation — so a knob change can be judged at once. */
export function Latency({ trace, generate }: { trace?: Record<string, number>; generate?: number | null }) {
  if (!trace) return null
  const parts = [
    ['برداری', trace.vector_ms ?? 0, 'bg-indigo-300/70'], ['متنی', trace.lexical_ms ?? 0, 'bg-cyan-300/70'],
    ['بازرتبه‌بندی', trace.rerank_ms ?? 0, 'bg-amber-300/70'], ['تولید پاسخ', generate ?? 0, 'bg-emerald-300/70'],
  ] as const
  const total = parts.reduce((s, [, v]) => s + v, 0) || 1
  return (
    <div className="space-y-2">
      <div className="flex h-2 overflow-hidden rounded-full bg-white/[.06]">{parts.map(([k, v, c]) => v > 0 && <div key={k} className={c} style={{ width: `${(v / total) * 100}%` }} title={`${k}: ${ms(v)}`} />)}</div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-white/45">{parts.map(([k, v, c]) => <span key={k} className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${c}`} />{k}: <span className="tnum text-white/65">{v ? ms(v) : '—'}</span></span>)}<span>مجموع: <span className="tnum text-white/65">{ms(total)}</span></span></div>
    </div>
  )
}
