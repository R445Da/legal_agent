import type { ReactNode } from 'react'
import { Eyebrow } from '@/components/ui/misc'

export function PageHeader({ eyebrow, title, summary, right }: { eyebrow: string; title: ReactNode; summary?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <Eyebrow>{eyebrow}</Eyebrow>
        <h1 className="mt-2 text-balance text-2xl font-semibold tracking-[-.02em] sm:text-3xl">{title}</h1>
        {summary && <p className="mt-2 max-w-2xl text-sm text-white/40">{summary}</p>}
      </div>
      {right && <div className="flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
    </div>
  )
}

export function KpiRow({ children }: { children: ReactNode }) {
  return <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
}
