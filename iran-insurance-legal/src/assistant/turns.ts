import type { AnswerResult, ConversationTurn, EditProposal, Intent, Provenance } from '@/api/types'
import type { Message } from './types'

/**
 * A message ⇄ a persisted turn (`/conversations`). The thread table is shared
 * with Streamlit, so a thread can be reopened in either UI: turns written here
 * carry the whole message in `extra` (plus `local_id`, so an edit outcome can
 * point back at its proposal), and turns written by Streamlit are read for the
 * few fields both UIs agree on.
 */

/** Never written: the row has its own id/role/text/intent/time, and these describe this tab only. */
const LOCAL_ONLY = new Set(['id', 'at', 'role', 'text', 'intent', 'streaming', 'restored', 'editState'])

export function toTurn(m: Message) {
  const extra: Record<string, unknown> = { local_id: m.id }
  for (const [key, value] of Object.entries(m)) if (!LOCAL_ONLY.has(key) && value !== undefined) extra[key] = value
  // The same facts under the names Streamlit's `_render` reads, so a thread
  // started here opens there: an archive turn without `run_id` raises in
  // `_render_pipeline`.
  if (m.runId) extra.run_id = m.runId
  if (m.clarify) extra.pending_text = m.clarify.original
  if (m.editOf) extra.kind = 'ack'
  return { role: m.role, text: m.text, intent: m.intent ?? null, model: m.result?.model ?? null, extra }
}

export function fromTurns(turns: ConversationTurn[], label: (intent: Intent) => string = (i) => i): Message[] {
  const messages = turns.map((turn): Message => {
    const { id, role, text, intent, model, created_at, local_id, ...extra } = turn
    const base = { role, text: text ?? '', at: created_at ?? new Date().toISOString(), restored: true }
    if (typeof local_id === 'string') {
      // Written by this app: the message as it was.
      return { ...(extra as Partial<Message>), ...base, id: local_id, ...(intent ? { intent: intent as Intent } : {}) }
    }
    // Written by Streamlit (`app/ui/views/agent.py::_say`).
    const m: Message = { ...base, id: `srv_${id}` }
    if (intent && role === 'assistant') Object.assign(m, { intent: intent as Intent, intentLabel: label(intent as Intent) })
    if (typeof extra.run_id === 'string') m.runId = extra.run_id
    const provenance = extra.provenance as Provenance | undefined
    const pending = extra.pending_edit as EditProposal | undefined
    if (role === 'assistant' && (pending?.entry_id || Array.isArray(provenance?.evidence))) {
      const result: AnswerResult = { intent: (intent ?? 'agent') as Intent, answer: m.text, model }
      if (pending?.entry_id) result.pending_edit = pending
      if (Array.isArray(provenance?.evidence)) result.provenance = provenance
      m.result = result
    }
    return m
  })

  // An edit gate's outcome is its own turn; fold it back onto the proposal.
  const byId = new Map(messages.map((m) => [m.id, m]))
  for (const m of messages) {
    const target = m.editOf ? byId.get(m.editOf) : undefined
    if (target && m.editOutcome) target.editState = m.editOutcome
  }
  return messages
}
