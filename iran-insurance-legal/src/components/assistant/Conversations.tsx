import { AnimatePresence, motion } from 'framer-motion'
import { History, Loader2, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { describeError } from '@/api/client'
import { useConversations } from '@/api/queries'
import { deleteConversation, openConversation } from '@/assistant/runtime'
import { ago, fa } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'

/**
 * «گفتگوها» — the saved threads (`/conversations`), shared with Streamlit's
 * assistant: reopen one, or delete it. Deleting clears the user's list, not
 * the archive's record of what was asked.
 */
export function ConversationsButton({ className, size = 'md' }: { className?: string; size?: 'sm' | 'md' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const current = useAssistant((s) => s.conversationId)
  const busy = useAssistant((s) => s.busy)
  const list = useConversations(open)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  const rows = list.data?.conversations ?? []
  return (
    <div ref={ref} className={cn('relative', className)}>
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open} aria-label="گفتگوهای ذخیره‌شده" title="گفتگوها"
        className={size === 'sm'
          ? 'flex h-8 w-8 items-center justify-center rounded-xl text-white/40 hover:bg-white/[.06] hover:text-white'
          : 'flex h-10 items-center gap-2 rounded-2xl border border-white/10 bg-white/[.04] px-3 text-xs text-white/60 hover:text-white'}>
        <History className={size === 'sm' ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
        {size === 'md' && <span className="hidden sm:inline">گفتگوها</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div role="dialog" aria-label="گفتگوها" initial={{ opacity: 0, y: -4, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4, scale: 0.98 }} transition={{ duration: 0.14 }}
            className="glass absolute end-0 top-full z-50 mt-2 w-[min(20rem,calc(100vw-2rem))] rounded-2xl p-1.5">
            <div className="px-3 pb-1.5 pt-1 text-[11px] text-white/35">گفتگوهای پیشین — برای باز کردن بزنید</div>
            <div className="max-h-80 overflow-y-auto">
              {list.isLoading && <div className="flex items-center gap-2 px-3 py-3 text-xs text-white/40"><Loader2 className="h-3.5 w-3.5 animate-spin" /> در حال بارگذاری…</div>}
              {list.error && <div className="px-3 py-3 text-xs text-rose-200/80">{describeError(list.error)}</div>}
              {list.isSuccess && rows.length === 0 && <div className="px-3 py-3 text-xs text-white/40">هنوز گفتگویی ذخیره نشده است.</div>}
              {rows.map((row) => (
                <div key={row.id} className={cn('group flex items-center gap-1 rounded-xl transition hover:bg-white/[.06]', row.id === current && 'bg-white/[.05]')}>
                  <button disabled={busy} onClick={() => { setOpen(false); void openConversation(row.id) }} className="min-w-0 flex-1 px-3 py-2 text-start disabled:opacity-40">
                    <div className="truncate text-xs text-white/80">{row.id === current && <span className="text-indigo-300">▸ </span>}{fa(row.title)}</div>
                    <div className="truncate text-[10.5px] text-white/35">
                      {fa(row.messages)} پیام{row.updated_at ? ` · ${ago(row.updated_at)}` : ''}{row.focus?.label ? ` · ${fa(row.focus.label)}` : ''}{row.source === 'ui' ? ' · استریم‌لیت' : ''}
                    </div>
                  </button>
                  <button onClick={() => void deleteConversation(row.id)} aria-label={`حذف گفتگوی «${row.title}»`} title="حذف"
                    className="me-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-white/25 opacity-60 transition hover:bg-rose-400/10 hover:text-rose-200 group-hover:opacity-100">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** What the current thread is working on — the entry an edit just landed on. */
export function FocusChip({ className }: { className?: string }) {
  const focus = useAssistant((s) => s.focus)
  if (!focus?.label) return null
  return (
    <span className={cn('inline-flex max-w-full items-center gap-1 truncate rounded-full border border-indigo-300/15 bg-indigo-300/[.06] px-2.5 py-1 text-[10.5px]', className)}>
      <span className="text-white/35">در حال کار روی</span> <span className="truncate text-indigo-100/85">{fa(focus.label)}</span>
    </span>
  )
}
