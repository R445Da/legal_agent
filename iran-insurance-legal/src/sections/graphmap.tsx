import { useMutation, useQuery } from '@tanstack/react-query'
import { ExternalLink, Loader2, Network, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { describeError } from '@/api/client'
import { api } from '@/api/endpoints'
import type { Graph } from '@/api/types'
import { fa } from '@/lib/format'
import { useAssistant } from '@/state/assistant'
import { usePublishContext } from '@/state/context'
import { useShell, type WorkspaceTab } from '@/state/shell'
import { Button } from '@/components/ui/button'
import { Card, Empty, Pill } from '@/components/ui/misc'
import { GraphView, NODE_FA } from '@/components/shared/GraphView'
import { PageHeader } from '@/components/shared/PageHeader'
import { LoadError, Skeleton } from '@/components/shared/Skeleton'

/**
 * ۲۰ نقشهٔ دانش — the archive as the Obsidian vault's graph: the notes under
 * «آرشیو/» and the wikilinks between them (GET /graph/vault). Every node opens
 * in Obsidian; cases and laws open here too.
 */
export function GraphMapView(_: { ws: WorkspaceTab }) {
  const vault = useQuery({ queryKey: ['vault'], queryFn: api.vault })
  const open = useShell((s) => s.open)
  const [kind, setKind] = useState('')
  const [confirm, setConfirm] = useState(false)
  usePublishContext('graphmap', { filters: kind ? { نوع: NODE_FA[kind] ?? kind } : undefined })
  const exportVault = useMutation({
    mutationFn: api.exportVault,
    onSuccess: () => { useAssistant.getState().toast({ tone: 'success', title: 'والت به‌روز شد', detail: 'یادداشت‌های «آرشیو/» از پایگاه‌داده بازنویسی شدند.' }); setConfirm(false); void vault.refetch() },
  })
  const graph: Graph | null = useMemo(() => {
    if (!vault.data) return null
    const nodes = vault.data.nodes.filter((n) => !kind || n.kind === kind)
    const byName = new Map(nodes.map((n) => [n.id, n]))
    return {
      nodes: nodes.map((n) => ({ id: n.id, type: String(n.kind ?? 'note'), label: String(n.name ?? n.id), case_number: n.case_number, uri: n.uri, record_id: n.record_id })),
      edges: vault.data.edges.filter((e) => byName.has(String(e.source)) && byName.has(String(e.target))).map((e) => ({ src: { type: String(byName.get(String(e.source))!.kind ?? 'note'), id: String(e.source) }, dst: { type: String(byName.get(String(e.target))!.kind ?? 'note'), id: String(e.target) }, rel: '' })) as unknown as Graph['edges'],
    }
  }, [vault.data, kind])
  if (vault.error) return <LoadError error={vault.error} retry={() => void vault.refetch()} />
  if (!vault.data) return <Skeleton />
  const kinds = Array.from(new Set(vault.data.nodes.map((n) => String(n.kind ?? 'note'))))
  return (
    <>
      <PageHeader eyebrow="۲۰ · نقشهٔ دانش" title="نقشهٔ دانش" summary="یادداشت‌های «آرشیو/» در والت Obsidian و پیوندهای میان آن‌ها — همان تصویری که نمای گراف Obsidian می‌کشد."
        right={<>{vault.data.exported && <Pill>{fa(vault.data.nodes.length)} یادداشت · {fa(vault.data.edges.length)} پیوند</Pill>}
          {!confirm ? <Button onClick={() => setConfirm(true)}><RefreshCw className="h-4 w-4" /> {vault.data.exported ? 'بازنویسی والت' : 'ساخت والت'}</Button>
            : <Button variant="approve" disabled={exportVault.isPending} onClick={() => exportVault.mutate()}>{exportVault.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null} تأیید — نوشتن در «آرشیو/»</Button>}</>} />
      {confirm && <div className="suggested mt-4 rounded-2xl p-3 text-[12px] leading-6 text-violet-50/85">پایگاه‌داده به‌صورت یادداشت در <span className="ltr font-mono">{vault.data.vault ?? 'graphify-out/obsidian'}/آرشیو</span> نوشته می‌شود. فقط پوشهٔ «آرشیو/» تغییر می‌کند. <button className="underline" onClick={() => setConfirm(false)}>انصراف</button></div>}
      {exportVault.error && <div className="mt-2 text-[12px] text-rose-200/80">{describeError(exportVault.error)}</div>}
      {!vault.data.exported ? (
        <Card className="mt-6"><Empty icon={<Network className="h-5 w-5" />} title="والت هنوز ساخته نشده است" detail="«ساخت والت» را بزنید یا «python -m scripts.export_vault» را اجرا کنید. والت در گیت نیست؛ یک کلون تازه یادداشتی ندارد." /></Card>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap gap-2">
            <button onClick={() => setKind('')} className={`rounded-full border px-3 py-1 text-[11.5px] ${!kind ? 'border-white/20 bg-white/10 text-white' : 'border-white/10 text-white/55'}`}>همه</button>
            {kinds.map((k) => <button key={k} onClick={() => setKind(k)} className={`rounded-full border px-3 py-1 text-[11.5px] ${kind === k ? 'border-white/20 bg-white/10 text-white' : 'border-white/10 text-white/55'}`}>{NODE_FA[k] ?? k} ({fa(vault.data.nodes.filter((n) => n.kind === k).length)})</button>)}
          </div>
          <Card className="mt-4 p-4">
            {graph && <GraphView graph={graph} height={560} onNode={(n) => {
              const node = n as Record<string, unknown>
              if (n.type === 'case' && node.case_number) open('cases', { record: String(node.case_number), label: fa(String(node.case_number)) })
              else if (n.type === 'law' && node.record_id) open('laws', { record: String(node.record_id) })
              else if (node.uri) window.open(String(node.uri), '_blank')
            }} />}
            <div className="mt-2 flex items-center gap-1 text-[11px] text-white/35"><ExternalLink className="h-3 w-3" /> یادداشت‌های دیگر در Obsidian باز می‌شوند.</div>
          </Card>
        </>
      )}
    </>
  )
}
