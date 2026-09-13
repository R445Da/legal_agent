import { Fragment, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * The subset of markdown the models actually emit — bold, italics, inline
 * code, links, headings, bullet/numbered lists, quotes and rules — rendered
 * inline with the app's typography. LLM answers arrive as plain strings;
 * without this, «**مهم**» shows up literally in the thread.
 */

const INLINE = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\))/g

export function renderInline(text: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*')) return <em key={i} className="text-white/95">{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={i} dir="ltr" className="mx-0.5 rounded-md bg-white/[.08] px-1.5 py-0.5 font-mono text-[.85em] text-cyan-100/90">{part.slice(1, -1)}</code>
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part)
    if (link) return <a key={i} href={link[2]} target="_blank" rel="noreferrer" className="text-indigo-200 underline decoration-indigo-300/40 underline-offset-2 hover:text-indigo-100">{link[1]}</a>
    return <Fragment key={i}>{part}</Fragment>
  })
}

const HEAD = /^(#{1,4})\s+(.*)$/
const BULLET = /^\s*[-•*]\s+/
const NUMBERED = /^\s*(\d+)[.)]\s+/
const QUOTE = /^>\s?/
const RULE = /^(-{3,}|\*{3,})$/

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = text.split('\n')
  const out: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null

  const flush = (key: string) => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    out.push(
      <Tag key={key} className={cn('my-1 space-y-0.5 ps-5', list.ordered ? 'list-decimal' : 'list-disc', 'marker:text-white/30')}>
        {list.items.map((item, i) => <li key={i}>{renderInline(item)}</li>)}
      </Tag>,
    )
    list = null
  }

  lines.forEach((line, i) => {
    const rule = RULE.exec(line.trim())
    const head = HEAD.exec(line)
    const bullet = BULLET.test(line)
    const numbered = NUMBERED.test(line)
    const quote = QUOTE.test(line)

    if (rule) { flush(`l${i}`); out.push(<hr key={i} className="my-2 border-white/[.08]" />); return }
    if (head) {
      flush(`l${i}`)
      const size = head[1].length <= 2 ? 'text-[14.5px]' : 'text-[13.5px]'
      out.push(<div key={i} className={cn('mt-2 font-semibold text-white/90', size)}>{renderInline(head[2])}</div>)
      return
    }
    if (bullet || numbered) {
      const item = line.replace(BULLET, '').replace(NUMBERED, '')
      if (!list || list.ordered !== numbered) { flush(`l${i}`); list = { ordered: numbered, items: [] } }
      list.items.push(item)
      return
    }
    flush(`l${i}`)
    if (quote) { out.push(<blockquote key={i} className="my-1 border-s-2 border-white/15 ps-3 text-white/60">{renderInline(line.replace(QUOTE, ''))}</blockquote>); return }
    if (line.trim()) out.push(<p key={i} className="leading-7">{renderInline(line)}</p>)
    else if (i < lines.length - 1) out.push(<div key={i} className="h-2" />)
  })
  flush('end')

  return <div className={className}>{out}</div>
}
