import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Empty } from '@/components/ui/misc'

export interface Column<T> { key: string; header: ReactNode; cell: (row: T) => ReactNode; className?: string; align?: 'end' | 'start'; hideOn?: 'sm' | 'md' | 'lg' }

const HIDE = { sm: 'hidden sm:table-cell', md: 'hidden md:table-cell', lg: 'hidden lg:table-cell' }

export function DataTable<T>({ rows, columns, rowKey, onRowClick, empty, rowClassName }: {
  rows: T[]
  columns: Column<T>[]
  rowKey: (r: T) => string
  onRowClick?: (r: T) => void
  empty?: ReactNode
  rowClassName?: (r: T) => string | undefined
}) {
  if (!rows.length) return <>{empty ?? <Empty title="موردی نیست" />}</>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-start text-xs">
        <thead>
          <tr className="text-white/30">
            {columns.map((c) => <th key={c.key} className={cn('whitespace-nowrap px-5 py-3 text-start font-normal', c.align === 'end' && 'text-end', c.hideOn && HIDE[c.hideOn], c.className)}>{c.header}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined}
              className={cn('border-t border-white/[.05] transition-colors', onRowClick && 'cursor-pointer hover:bg-white/[.025]', rowClassName?.(r))}>
              {columns.map((c) => <td key={c.key} className={cn('px-5 py-3.5 align-middle', c.align === 'end' && 'tnum text-end', c.hideOn && HIDE[c.hideOn], c.className)}>{c.cell(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
