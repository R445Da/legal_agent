import { fa } from '@/lib/format'
import { useShell } from '@/state/shell'

type Lesson = { case_number: string; title?: string; outcome?: string; point?: string }
const GROUPS: [keyof LessonSet, string, string][] = [
  ['worked', 'به نتیجه رسید', 'text-emerald-200/80'], ['failed', 'ناموفق', 'text-rose-200/80'], ['pending', 'جاری', 'text-white/50'],
]
type LessonSet = { worked?: Lesson[]; failed?: Lesson[]; pending?: Lesson[] }

/** What past similar cases teach (`similar.outcome_lessons`) — history, not a prediction. */
export function Lessons({ lessons }: { lessons: unknown }) {
  const open = useShell((s) => s.open)
  if (!lessons || typeof lessons !== 'object' || Array.isArray(lessons)) return typeof lessons === 'string' && lessons ? <p className="text-[12px] text-white/55">{lessons}</p> : null
  const set = lessons as LessonSet
  if (!GROUPS.some(([k]) => set[k]?.length)) return null
  return (
    <div className="space-y-2 rounded-2xl border border-white/[.06] bg-white/[.02] p-3">
      <div className="text-[11px] text-white/40">درس‌های پرونده‌های مشابه — تاریخی است، نه پیش‌بینی</div>
      {GROUPS.filter(([k]) => set[k]?.length).map(([k, label, tone]) => (
        <div key={k}>
          <div className={`text-[11px] font-medium ${tone}`}>{label} ({fa(set[k]!.length)})</div>
          {set[k]!.slice(0, 4).map((l) => (
            <button key={l.case_number} onClick={() => open('cases', { record: l.case_number, label: fa(l.case_number) })} className="block w-full truncate text-start text-[11.5px] leading-6 text-white/60 hover:text-white">
              <span className="ltr font-mono text-[10.5px] text-white/40">{fa(l.case_number)}</span> — {fa(l.outcome || l.title || '')}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}
