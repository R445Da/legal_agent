import { ChevronDown, FileText } from 'lucide-react'
import { useState } from 'react'
import type { Context } from '@/api/types'
import { fa, pct } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useShell } from '@/state/shell'

/** Numbered excerpts behind an answer — every [n] in the text points here. */
export function Citations({ contexts, open: initiallyOpen = false, title = 'مستندات' }: { contexts: Context[]; open?: boolean; title?: string }) {
  const [open, setOpen] = useState(initiallyOpen)
  const openSection = useShell((s) => s.open)
  if (!contexts.length) return null
  return (
    <div className="rounded-2xl border border-white/[.06] bg-white/[.02]">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-3 py-2 text-[11.5px] text-white/55 hover:text-white">
        <span>{title} ({fa(contexts.length)} قطعه)</span>
        <ChevronDown className={cn('h-4 w-4 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <ol className="space-y-2 px-3 pb-3">
          {contexts.map((c) => (
            <li key={`${c.n}-${c.chunk_id ?? c.document_id ?? c.title}`} className="rounded-xl border border-white/[.05] bg-ink-900/40 p-2.5">
              <div className="flex items-center justify-between gap-2 text-[11px]">
                <span className="flex min-w-0 items-center gap-1.5 text-white/75"><span className="tnum rounded-md bg-indigo-400/15 px-1.5 text-indigo-100">[{fa(c.n)}]</span><span className="truncate">{c.title ?? c.source}</span></span>
                <span className="flex shrink-0 items-center gap-2 text-white/35">
                  {typeof c.similarity === 'number' && <span className="tnum">{pct(c.similarity)}</span>}
                  {c.document_id && <button onClick={() => openSection('documents', { record: c.document_id!, label: (c.title ?? 'سند').slice(0, 24), origin: 'tab' })} className="flex items-center gap-1 hover:text-white"><FileText className="h-3 w-3" /> سند</button>}
                </span>
              </div>
              <p className="mt-1.5 line-clamp-4 whitespace-pre-line text-[11.5px] leading-6 text-white/50">{c.text}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
