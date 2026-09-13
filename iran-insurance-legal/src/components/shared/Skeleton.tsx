import { ServerOff } from 'lucide-react'
import { describeError } from '@/api/client'
import { Button } from '@/components/ui/button'

export function Skeleton() {
  return (
    <div className="animate-pulse space-y-4" aria-busy>
      <div className="h-4 w-32 rounded-full bg-white/[.05]" />
      <div className="h-8 w-72 rounded-full bg-white/[.06]" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 rounded-3xl bg-white/[.04]" />)}</div>
      <div className="h-72 rounded-3xl bg-white/[.03]" />
    </div>
  )
}

/** A failed load, said plainly, with a retry. */
export function LoadError({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-20 text-center">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-rose-300/15 bg-rose-400/[.06] text-rose-200"><ServerOff className="h-5 w-5" /></div>
      <div className="text-sm font-medium text-white/85">بارگذاری ناموفق بود</div>
      <div className="mt-1 max-w-md text-xs leading-6 text-white/45">{describeError(error)}</div>
      {retry && <Button className="mt-4" onClick={retry}>تلاش دوباره</Button>}
    </div>
  )
}
