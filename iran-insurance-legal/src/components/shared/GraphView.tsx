import { useEffect, useMemo, useRef, useState } from 'react'
import type { Graph, GraphNode } from '@/api/types'
import { cn } from '@/lib/utils'

/**
 * A neighbourhood graph drawn without a graph library: a small force layout
 * (repulsion + springs + centering), rendered to SVG. Replaces the Streamlit
 * graphviz charts for case / entity / law neighbourhoods and the vault map.
 */
const TYPE_COLOR: Record<string, string> = {
  case: '#67e8f9', law: '#fcd34d', person: '#c4b5fd', org: '#6ee7b7', court: '#fda4af', label: '#7dd3fc', tag: '#7dd3fc', note: '#e2e8f0', entry: '#94a3b8', document: '#94a3b8',
}
export const NODE_FA: Record<string, string> = { case: 'پرونده', law: 'ماده', person: 'شخص', org: 'سازمان', court: 'مرجع', label: 'برچسب', tag: 'برچسب', note: 'یادداشت', entry: 'مدخل', document: 'سند' }

interface P { x: number; y: number; vx: number; vy: number }

const keyOf = (type: string | undefined, id: string) => (type ? `${type}:${id}` : id)
function endKey(end: unknown): string {
  if (end && typeof end === 'object') { const o = end as { type?: string; id: string }; return keyOf(o.type, o.id) }
  return String(end)
}

export function GraphView({ graph, height = 420, focus, onNode, className }: { graph: Graph; height?: number; focus?: string; onNode?: (n: GraphNode) => void; className?: string }) {
  const width = 900
  // Engine graphs key nodes by (type, id) and edges carry {type, id} ends;
  // the vault map uses plain string ids. Normalise both to one key space.
  const nodes = useMemo(() => graph.nodes.slice(0, 260).map((n) => ({ ...n, key: keyOf(n.type, n.id) })), [graph.nodes])
  const ids = useMemo(() => new Set(nodes.map((n) => n.key)), [nodes])
  const edges = useMemo(() => graph.edges.map((e) => ({ s: endKey((e as Record<string, unknown>).src ?? (e as Record<string, unknown>).source), t: endKey((e as Record<string, unknown>).dst ?? (e as Record<string, unknown>).target) })).filter((e) => ids.has(e.s) && ids.has(e.t)), [graph.edges, ids])
  const focusKey = focus ? nodes.find((n) => n.id === focus || n.key === focus || (n as Record<string, unknown>).root)?.key : nodes.find((n) => (n as Record<string, unknown>).root)?.key
  const pos = useRef<Record<string, P>>({})
  const [, setTick] = useState(0)
  const [hover, setHover] = useState<string | null>(null)

  useEffect(() => {
    const p: Record<string, P> = {}
    nodes.forEach((n, i) => {
      const a = (i / Math.max(nodes.length, 1)) * Math.PI * 2
      const r = n.key === focusKey ? 0 : 120 + (i % 5) * 18
      p[n.key] = pos.current[n.key] ?? { x: width / 2 + Math.cos(a) * r, y: height / 2 + Math.sin(a) * r, vx: 0, vy: 0 }
    })
    pos.current = p
    let frame = 0
    let raf = 0
    const step = () => {
      const list = Object.entries(pos.current)
      for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
        const [, a] = list[i]; const [, b] = list[j]
        let dx = a.x - b.x; let dy = a.y - b.y
        const d2 = Math.max(dx * dx + dy * dy, 40)
        const f = 1800 / d2
        dx *= f / Math.sqrt(d2); dy *= f / Math.sqrt(d2)
        a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy
      }
      for (const e of edges) {
        const a = pos.current[e.s]; const b = pos.current[e.t]
        const dx = b.x - a.x; const dy = b.y - a.y
        const d = Math.sqrt(dx * dx + dy * dy) || 1
        const f = (d - 95) * 0.012
        a.vx += (dx / d) * f; a.vy += (dy / d) * f; b.vx -= (dx / d) * f; b.vy -= (dy / d) * f
      }
      for (const [id, q] of list) {
        q.vx += (width / 2 - q.x) * 0.004; q.vy += (height / 2 - q.y) * 0.006
        if (id === focusKey) { q.vx += (width / 2 - q.x) * 0.1; q.vy += (height / 2 - q.y) * 0.1 }
        q.x += q.vx *= 0.55; q.y += q.vy *= 0.55
        q.x = Math.min(width - 30, Math.max(30, q.x)); q.y = Math.min(height - 24, Math.max(24, q.y))
      }
      setTick((t) => t + 1)
      if (++frame < 160) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, focusKey, height])

  if (!nodes.length) return <div className="py-10 text-center text-xs text-white/35">گرافی برای نمایش نیست.</div>
  const near = hover ? new Set(edges.flatMap((e) => (e.s === hover ? [e.t] : e.t === hover ? [e.s] : []))) : null

  return (
    <div className={cn('overflow-hidden rounded-2xl border border-white/[.06] bg-ink-900/60', className)}>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="گراف ارتباطات">
        {edges.map((e, i) => {
          const a = pos.current[e.s]; const b = pos.current[e.t]
          if (!a || !b) return null
          const lit = hover && (e.s === hover || e.t === hover)
          return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={lit ? 'rgba(255,255,255,.45)' : 'rgba(255,255,255,.10)'} strokeWidth={lit ? 1.4 : 1} />
        })}
        {nodes.map((n) => {
          const q = pos.current[n.key]
          if (!q) return null
          const dim = near && n.key !== hover && !near.has(n.key)
          const r = n.key === focusKey ? 11 : n.type === 'case' ? 7 : 6
          return (
            <g key={n.key} transform={`translate(${q.x},${q.y})`} className={cn(onNode && 'cursor-pointer')} opacity={dim ? 0.25 : 1}
              onMouseEnter={() => setHover(n.key)} onMouseLeave={() => setHover(null)} onClick={() => onNode?.(n)}>
              <circle r={r + 5} fill={TYPE_COLOR[n.type] ?? '#e2e8f0'} opacity={0.12} />
              <circle r={r} fill={TYPE_COLOR[n.type] ?? '#e2e8f0'} stroke="#090b11" strokeWidth={1.5} />
              {(n.key === focusKey || hover === n.key || nodes.length < 40) && (
                <text y={-r - 6} textAnchor="middle" fontSize={11} fill="rgba(255,255,255,.8)" style={{ fontFamily: 'Vazirmatn', paintOrder: 'stroke', stroke: '#090b11', strokeWidth: 3 }}>{String(n.label ?? n.id).slice(0, 34)}</text>
              )}
            </g>
          )
        })}
      </svg>
      <div className="flex flex-wrap gap-3 border-t border-white/[.05] px-3 py-2 text-[10.5px] text-white/45">
        {Array.from(new Set(nodes.map((n) => n.type))).map((t) => <span key={t} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[t] ?? '#e2e8f0' }} />{NODE_FA[t] ?? t}</span>)}
      </div>
    </div>
  )
}
