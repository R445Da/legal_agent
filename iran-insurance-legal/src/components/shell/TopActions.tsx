import { Command, Inbox, LayoutGrid } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api } from '@/api/endpoints'
import { useArchive } from '@/api/queries'
import { fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { useShell } from '@/state/shell'
import { Kbd } from '@/components/ui/misc'

export function useInboxCount() {
  const runs = useAssistant((s) => s.runs)
  const { data } = useArchive()
  const serverRuns = useQuery({ queryKey: ['runs'], queryFn: () => api.runs(30), refetchInterval: 30_000 })
  return useMemo(() => {
    const ids = new Set<string>()
    Object.values(runs).filter((r) => r.status === 'awaiting_input' || r.status === 'failed').forEach((r) => ids.add(r.id))
    serverRuns.data?.runs.filter((r) => r.status === 'awaiting_input' || r.status === 'failed').forEach((r) => ids.add(r.id))
    return ids.size + (data?.review_queue.length ?? 0)
  }, [runs, data, serverRuns.data])
}

export function InboxButton({ className }: { className?: string }) {
  const setInbox = useShell((s) => s.setInbox)
  const n = useInboxCount()
  return (
    <button onClick={() => setInbox(true)} aria-label={`صندوق کارها، ${fa(n)} مورد`} title="صندوق کارها"
      className={cn('relative flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-white/70 transition hover:bg-white/[.08] hover:text-white', className)}>
      <Inbox className="h-[18px] w-[18px]" />
      {n > 0 && <span className="tnum absolute -end-1 -top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-amber-300 px-1 text-[10px] font-semibold text-amber-950">{fa(n)}</span>}
    </button>
  )
}

export function PanelButton({ className }: { className?: string }) {
  const goPanel = useShell((s) => s.goPanel)
  return <button onClick={goPanel} aria-label="پیشخوان بخش‌ها" title="پیشخوان بخش‌ها" className={cn('flex h-10 w-10 items-center justify-center rounded-2xl border border-white/10 bg-white/[.04] text-white/70 hover:bg-white/[.08] hover:text-white', className)}><LayoutGrid className="h-[18px] w-[18px]" /></button>
}

export function PaletteButton({ className, label = 'جستجو' }: { className?: string; label?: string }) {
  const setPalette = useShell((s) => s.setPalette)
  const mac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
  return (
    <button onClick={() => setPalette(true)} className={cn('flex h-10 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.04] px-3 text-xs text-white/55 transition hover:bg-white/[.08] hover:text-white', className)}>
      <Command className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{label}</span>
      <Kbd className="ltr hidden sm:inline-flex">{mac ? '⌘' : 'Ctrl'} K</Kbd>
    </button>
  )
}

/** The product mark: بیمه ایران حقوقی. */
export function BrandMark({ onClick, compact }: { onClick?: () => void; compact?: boolean }) {
  return (
    <button onClick={onClick} className="group flex items-center gap-3 text-start" aria-label="بیمه ایران حقوقی — خانه">
      <span className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-white/10 bg-white/[.06]">
        <span className="orb-conic absolute inset-[9px] rounded-full opacity-90 transition group-hover:scale-110" />
        <span className="absolute inset-[13px] rounded-full bg-ink-850" />
      </span>
      {!compact && (
        <span className="hidden sm:block">
          <span className="block text-[15px] font-bold leading-5 tracking-tight">بیمه ایران حقوقی</span>
          <span className="block text-[11px] text-white/40">دستیار حقوقی شرکت سهامی بیمه ایران</span>
        </span>
      )}
    </button>
  )
}
