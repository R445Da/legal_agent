import { fa } from '@/lib/format'

export const axis = { tick: { fill: 'rgba(255,255,255,.4)', fontSize: 10, fontFamily: 'Vazirmatn' }, axisLine: false, tickLine: false } as const
export const tooltipStyle = { contentStyle: { background: '#10121c', border: '1px solid rgba(255,255,255,.08)', borderRadius: 12, fontSize: 12, color: '#f7f7fb', direction: 'rtl' as const, fontFamily: 'Vazirmatn' }, labelStyle: { color: 'rgba(255,255,255,.5)' } } as const
export const faTick = (v: number | string) => fa(typeof v === 'number' ? v : String(v))
