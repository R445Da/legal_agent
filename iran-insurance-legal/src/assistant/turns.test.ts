import { describe, expect, it } from 'vitest'
import type { ConversationTurn, EditProposal } from '@/api/types'
import { fromTurns, toTurn } from './turns'
import type { Message } from './types'

const proposal: EditProposal = {
  entry_id: 'e1', entry_title: 'بازیافت خسارت', field: 'entities', facet: 'case_number', field_fa: 'شمارهٔ پرونده',
  old: '۱۴۰۰۱۱۱', old_text: '۱۴۰۰۱۱۱', new: '۱۴۰۰۲۲۲', new_text: '۱۴۰۰۲۲۲', patch: { entities: { case_number: '۱۴۰۰۲۲۲' } }, op: 'edit',
}

/** What the server hands back for a turn this app wrote: the row's columns plus `extra` spread on top. */
const stored = (m: Message, id: string): ConversationTurn => {
  const t = toTurn(m)
  return { id, role: t.role, text: t.text, intent: t.intent, model: t.model, created_at: '2026-09-13T10:00:00Z', ...t.extra }
}

describe('toTurn / fromTurns', () => {
  it('reopens a message as it was, marked as restored', () => {
    const m: Message = { id: 'msg_a', role: 'assistant', at: 'x', text: 'پاسخ', streaming: true, intent: 'agent', intentLabel: 'پژوهش عاملی', why: ['نوع پیام'], result: { intent: 'agent', answer: 'پاسخ', pending_edit: proposal } }
    const [back] = fromTurns([stored(m, 'row1')])
    expect(back).toMatchObject({ id: 'msg_a', role: 'assistant', text: 'پاسخ', intent: 'agent', intentLabel: 'پژوهش عاملی', why: ['نوع پیام'], restored: true })
    expect(back.result?.pending_edit?.entry_id).toBe('e1')
    expect(back.streaming).toBeUndefined()
  })

  it('never writes what only this tab knows', () => {
    const t = toTurn({ id: 'msg_b', role: 'user', at: 'x', text: 'سلام', streaming: true, restored: true, editState: 'done' })
    expect(t.extra).toEqual({ local_id: 'msg_b' })
  })

  it("folds an edit gate's outcome back onto the proposal it settled", () => {
    const ask: Message = { id: 'msg_p', role: 'assistant', at: 'x', text: '', result: { intent: 'agent', pending_edit: proposal } }
    const ack: Message = { id: 'msg_q', role: 'assistant', at: 'x', text: 'ثبت شد', editOf: 'msg_p', editOutcome: 'done' }
    const [p] = fromTurns([stored(ask, '1'), stored(ack, '2')])
    expect(p.editState).toBe('done')
  })

  it("writes what Streamlit's renderer reads under its own names", () => {
    expect(toTurn({ id: 'r', role: 'assistant', at: 'x', text: '', intent: 'archive', runId: 'run7' }).extra).toMatchObject({ run_id: 'run7', runId: 'run7' })
    expect(toTurn({ id: 'c', role: 'assistant', at: 'x', text: '؟', clarify: { original: 'متن', options: ['query'] } }).extra).toMatchObject({ pending_text: 'متن' })
    expect(toTurn({ id: 'k', role: 'assistant', at: 'x', text: 'ثبت شد', editOf: 'p', editOutcome: 'done' }).extra).toMatchObject({ kind: 'ack' })
  })

  it('reads a turn Streamlit wrote for the fields both UIs share', () => {
    const turns: ConversationTurn[] = [
      { id: 's1', role: 'assistant', text: 'پیشنهاد', intent: 'agent', model: 'mock', created_at: null, pending_edit: proposal, reasoning: 'x', latency_ms: 12 },
      { id: 's2', role: 'assistant', text: 'در انتظار', intent: 'archive', model: null, created_at: null, run_id: 'run9', kind: 'ack' },
    ]
    const [edit, run] = fromTurns(turns, (i) => `«${i}»`)
    expect(edit).toMatchObject({ id: 'srv_s1', intent: 'agent', intentLabel: '«agent»', restored: true })
    expect(edit.result?.pending_edit?.field_fa).toBe('شمارهٔ پرونده')
    expect(edit).not.toHaveProperty('reasoning')
    expect(run.runId).toBe('run9')
    expect(run.result).toBeUndefined()
  })
})
