import type { Intent, RunMode } from '@/api/types'
import { cn } from '@/lib/utils'
import { useSettings } from '@/state/settings'

/**
 * The two per-message choices beside the composer, as in Streamlit:
 * «نوع پیام» (let the router decide, or pin an intent) and «حالت ثبت مدخل»
 * (how often a filing stops for your approval).
 */
const INTENTS: { id: Intent | 'auto'; label: string }[] = [
  { id: 'auto', label: 'تشخیص خودکار' }, { id: 'query', label: 'پرسش از اسناد' }, { id: 'law', label: 'پرسش از قوانین' },
  { id: 'cases', label: 'بایگانی پرونده‌ها' }, { id: 'agent', label: 'پژوهش عاملی' }, { id: 'archive', label: 'ثبت مطلب جدید' },
  { id: 'analytics', label: 'آمار آرشیو' }, { id: 'chat', label: 'گفت‌وگو' },
]
const MODES: { id: RunMode; label: string; help: string }[] = [
  { id: 'review', label: 'تأیید یک‌باره', help: 'همه‌چیز اجرا می‌شود و فقط یک‌بار برای بازبینی می‌ایستد.' },
  { id: 'conversation', label: 'گفتگویی', help: 'دستیار فیلدهای خالی را یکی‌یکی در گفتگو می‌پرسد.' },
  { id: 'steps', label: 'گام‌به‌گام', help: 'در هر مرحله برای تأیید شما می‌ایستد.' },
  { id: 'auto', label: 'خودکار', help: 'بدون توقف ثبت می‌کند — فقط برای ورودی مطمئن.' },
]

export function MessageControls({ className, compact }: { className?: string; compact?: boolean }) {
  const { intent, runMode, set } = useSettings()
  const field = cn('h-8 rounded-xl border border-white/10 bg-white/[.04] px-2 text-[11.5px] text-white/75 outline-none focus:border-indigo-300/40', compact ? 'max-w-[44%]' : '')
  return (
    <div className={cn('flex flex-wrap items-center justify-center gap-2', className)}>
      <label className="flex items-center gap-1.5 text-[11px] text-white/35">
        {!compact && 'نوع پیام'}
        <select aria-label="نوع پیام" className={field} value={intent} onChange={(e) => set({ intent: e.target.value as Intent | 'auto' })}>
          {INTENTS.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-1.5 text-[11px] text-white/35" title={MODES.find((m) => m.id === runMode)?.help}>
        {!compact && 'حالت ثبت مدخل'}
        <select aria-label="حالت ثبت مدخل" className={field} value={runMode} onChange={(e) => set({ runMode: e.target.value as RunMode })}>
          {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </label>
    </div>
  )
}
