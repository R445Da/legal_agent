import { ChevronLeft } from 'lucide-react'
import { Fragment } from 'react'
import { useCurrentContext } from '@/state/context'
import { useShell } from '@/state/shell'
import { GROUPS, sectionById } from '@/sections/registry'

/** بایگانی ← پرونده‌ها ← ۱۴۰۴۷۰۵۰۲۵ ← گراف و مستندات */
export function ContextBreadcrumb() {
  const ctx = useCurrentContext()
  const { goPanel, focusInner } = useShell()
  if (!ctx.section) return null
  const s = sectionById(ctx.section)
  const crumbs: { label: string; onClick?: () => void }[] = [
    { label: GROUPS.find((g) => g.id === s.group)!.title, onClick: goPanel },
    { label: s.title, onClick: () => focusInner(null) },
    ...(ctx.entityId ? [{ label: ctx.entityLabel ?? ctx.entityId.slice(0, 14) }] : ctx.tabLabel ? [{ label: ctx.tabLabel }] : []),
    ...(ctx.view ? [{ label: ctx.view }] : []),
  ]
  return (
    <nav aria-label="زمینه" className="flex min-w-0 items-center gap-1 text-[11px] text-white/35">
      {crumbs.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <ChevronLeft className="h-3 w-3 shrink-0 text-white/20" />}
          {c.onClick && i < crumbs.length - 1
            ? <button onClick={c.onClick} className="truncate hover:text-white/80">{c.label}</button>
            : <span className={i === crumbs.length - 1 ? 'truncate text-white/65' : 'truncate'}>{c.label}</span>}
        </Fragment>
      ))}
    </nav>
  )
}
