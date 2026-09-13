import { api } from '@/api/endpoints'
import { archiveKey } from '@/api/queries'
import { describeError } from '@/api/client'
import type { AnswerResult, ArchiveState, EntryRun, Intent } from '@/api/types'
import { queryClient } from '@/lib/queryClient'
import { sleep } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { currentContext } from '@/state/context'
import { useSettings } from '@/state/settings'
import { serialize, useShell } from '@/state/shell'
import { sectionById } from '@/sections/registry'
import { parseNavigation } from './intent'
import { speak } from './speak'

/**
 * The assistant runtime:
 *
 *   message → (navigation?) → route (orchestrator.route) → executor → answer
 *                                                         ↘ archive → entry run
 *                                                             → human gate(s) → commit
 *
 * Only a human click at a gate (`approveGate`) moves a filing towards the
 * archive; the model's draft is shown as a suggestion until then. The user
 * sees operational steps, never model reasoning.
 */

type Origin = 'home' | 'assistant' | 'palette' | 'voice'

const store = () => useAssistant.getState()
const shell = () => useShell.getState()

export const INTENT_FA: Record<Intent, string> = {
  query: 'پرسش از اسناد', law: 'پرسش از قوانین', cases: 'جستجوی بایگانی پرونده‌ها', agent: 'پژوهش عاملی',
  archive: 'ثبت مطلب جدید', analytics: 'آمار آرشیو', chat: 'گفت‌وگو', unclear: 'نامشخص',
}

let idleTimer: ReturnType<typeof setTimeout> | undefined
function settle(state: 'completed' | 'error' | 'idle' | 'awaiting' = 'completed') {
  clearTimeout(idleTimer)
  store().setOrb(state)
  if (state === 'idle' || state === 'awaiting') return
  idleTimer = setTimeout(() => {
    const waiting = Object.values(store().runs).some((r) => r.status === 'awaiting_input')
    store().setOrb(waiting ? 'awaiting' : 'idle')
  }, state === 'error' ? 2600 : 1800)
}

async function stream(id: string, text: string) {
  store().setOrb('responding')
  const step = Math.max(3, Math.round(text.length / 70))
  for (let i = step; i < text.length; i += step) {
    store().patch(id, { text: text.slice(0, i), streaming: true })
    await sleep(12)
  }
  store().patch(id, { text, streaming: false })
}

export const refreshArchive = () => queryClient.invalidateQueries({ predicate: (q) => !['options', 'models', 'health'].includes(String(q.queryKey[0])) })

export async function ask(text: string, origin: Origin = 'assistant', forced?: Intent) {
  const trimmed = text.trim()
  const a = store()
  if (!trimmed || a.busy) return
  const ctx = currentContext()
  a.setBusy(true)
  a.push({ role: 'user', text: trimmed, context: ctx, intent: forced })
  a.setOrb('processing')
  try {
    // Spoken session commands («گفتگوی جدید», «پروندهٔ جدید», «توقف»).
    if (origin === 'voice') {
      const { command } = await api.command(trimmed).catch(() => ({ command: null }))
      if (command && (await runCommand(command))) return
    }

    // A conversation-mode filing is waiting for this reply.
    const waitingRun = a.conversationRun
    if (waitingRun && !forced) return await replyToRun(waitingRun, trimmed)

    // Explicit navigation needs no model call.
    if (!forced) {
      const state = queryClient.getQueryData<ArchiveState>(archiveKey())
      const nav = parseNavigation(trimmed, state)
      if (nav) {
        a.setOrb('working')
        await sleep(220)
        shell().open(nav.section, { tab: nav.tab, record: nav.record, label: nav.label, origin: origin === 'home' || origin === 'voice' ? 'intent' : 'tab' })
        a.setBanner({ text: nav.reply, why: nav.why, view: serialize(shell()) })
        a.log({ kind: 'routed', text: nav.reply, refs: nav.record ? [nav.record] : [] })
        const id = a.push({ role: 'assistant', text: '', why: nav.why, route: { section: nav.section, tab: nav.tab, record: nav.record, label: sectionById(nav.section).title } })
        await stream(id, nav.reply)
        return settle()
      }
    }

    // Understand: the forced intent, the «نوع پیام» setting, or the engine's router.
    const setting = useSettings.getState().intent
    let intent: Intent = forced ?? (setting !== 'auto' ? setting : 'unclear')
    let clarification = ''
    const why: string[] = []
    if (!forced && setting === 'auto') {
      const r = await api.route(trimmed)
      intent = r.intent
      clarification = r.clarification
      why.push(`نوع پیام: «${r.label}» — ${r.reason}`)
    } else why.push(forced ? `نوع پیام را خودتان انتخاب کردید: «${INTENT_FA[intent]}»` : `«نوع پیام» در تنظیمات: «${INTENT_FA[intent]}»`)

    if (intent === 'unclear') {
      const id = a.push({ role: 'assistant', text: '', intent, intentLabel: INTENT_FA.unclear, clarify: { original: trimmed, options: ['query', 'law', 'cases', 'archive', 'analytics'] }, why })
      await stream(id, clarification || 'منظورتان پرسش از آرشیو است، ثبت مطلب جدید، یا آمار؟')
      return settle('idle')
    }

    if (intent === 'archive') return await startFiling(trimmed, why, origin)

    a.setOrb('working')
    let result: AnswerResult
    let scope: string | undefined
    if (intent === 'query' && ctx.entityKind === 'case' && ctx.documentIds?.length) {
      result = { ...(await api.ask(trimmed, { document_ids: ctx.documentIds })), intent: 'query' }
      scope = `فقط از اسناد پروندهٔ ${ctx.entityLabel ?? ctx.entityId}`
      why.push(`زمینه: پروندهٔ باز در «پرونده‌ها» — ${ctx.documentIds.length} سند`)
    } else if (intent === 'query') {
      result = { ...(await api.ask(trimmed)), intent: 'query' }
    } else {
      result = await api.assistant(trimmed, intent)
    }
    const answer = result.answer ?? result.summary ?? ''
    const id = a.push({ role: 'assistant', text: '', intent, intentLabel: INTENT_FA[intent], result, scope, why })
    a.log({ kind: 'answered', text: `پاسخ «${INTENT_FA[intent]}»: ${trimmed.slice(0, 60)}`, refs: result.answer_id ? [result.answer_id] : [] })
    await stream(id, answer || (intent === 'analytics' ? 'آمار آرشیو آماده شد.' : 'پاسخی برنگشت.'))
    if (useSettings.getState().speakReplies) speak(answer)
    settle()
  } catch (error) {
    a.push({ role: 'assistant', text: '', error: describeError(error), retry: { text: trimmed, intent: forced } })
    settle('error')
  } finally {
    store().setBusy(false)
  }
}

async function runCommand(command: string) {
  const a = store()
  if (command === 'new_chat') {
    a.clear()
    a.toast({ tone: 'info', title: 'گفتگوی جدید آغاز شد' })
    settle('idle')
    return true
  }
  if (command === 'stop' && a.conversationRun) {
    await abandonRun(a.conversationRun)
    return true
  }
  if (command === 'new_case') {
    a.push({ role: 'assistant', text: 'متن جلسه یا سند را بگویید یا بنویسید — آن را به‌عنوان مطلب جدید ثبت می‌کنم.' })
    useSettings.getState().set({ intent: 'archive' })
    settle('idle')
    return true
  }
  return false
}

// ------------------------------------------------------------- entry filings

async function startFiling(text: string, why: string[], origin: Origin) {
  const a = store()
  a.setOrb('working')
  const mode = useSettings.getState().runMode
  const reply = await api.startRun(text, mode)
  a.setRun(reply.run)
  a.log({ kind: 'filing', text: `ثبت مطلب جدید آغاز شد (${mode === 'review' ? 'تأیید یک‌باره' : mode === 'steps' ? 'گام‌به‌گام' : mode === 'auto' ? 'خودکار' : 'گفتگویی'})`, refs: [reply.run.id] })
  if (reply.waiting) a.set({ conversationRun: reply.run.id })
  const id = a.push({ role: 'assistant', text: '', intent: 'archive', intentLabel: INTENT_FA.archive, runId: reply.run.id, why: [...why, 'پیش‌نویس مدل تا تأیید شما در آرشیو نوشته نمی‌شود'] })
  if (origin === 'assistant') shell().setAssistant(true)
  await stream(id, reply.message ?? runSummary(reply.run))
  if (reply.run.status === 'committed') onCommitted(reply.run)
  settle(reply.run.status === 'awaiting_input' || reply.waiting ? 'awaiting' : reply.run.status === 'failed' ? 'error' : 'completed')
}

export function runSummary(run: EntryRun) {
  if (run.status === 'committed') return 'مدخل در آرشیو ثبت شد.'
  if (run.status === 'failed') return 'یکی از گام‌های خط لوله ناموفق بود — می‌توانید دوباره تلاش کنید.'
  if (run.status === 'abandoned') return 'این ثبت متوقف شد.'
  const awaiting = run.steps.find((s) => s.status === 'awaiting_input')
  if (awaiting) return awaiting.step_id === 'labels' && (awaiting.payload as { mode?: string }).mode === 'review'
    ? 'پیش‌نویس مدخل آماده است — یک‌بار بازبینی کنید و تأیید کنید.'
    : `در انتظار تأیید شما — «${awaiting.label}».`
  return 'خط لوله در حال اجراست…'
}

async function replyToRun(runId: string, text: string) {
  const a = store()
  a.setOrb('working')
  try {
    const reply = await api.replyRun(runId, text)
    a.setRun(reply.run)
    a.set({ conversationRun: reply.waiting ? runId : null })
    const id = a.push({ role: 'assistant', text: '', intent: 'archive', intentLabel: INTENT_FA.archive, runId })
    await stream(id, reply.message ?? runSummary(reply.run))
    if (reply.run.status === 'committed') onCommitted(reply.run)
    settle(reply.waiting ? 'awaiting' : 'completed')
  } finally {
    store().setBusy(false)
  }
}

/** The human checkpoint: apply the user's edits to the awaiting gate and continue. */
export async function approveGate(runId: string, patch: Record<string, unknown>) {
  const a = store()
  a.setOrb('working')
  try {
    const run = await api.advanceRun(runId, patch)
    a.setRun(run)
    a.log({ kind: 'gate', text: 'گام تأیید شد و خط لوله ادامه یافت', refs: [runId] })
    if (run.status === 'committed') onCommitted(run)
    settle(run.status === 'awaiting_input' ? 'awaiting' : run.status === 'failed' ? 'error' : 'completed')
    return run
  } catch (error) {
    a.toast({ tone: 'error', title: 'ادامهٔ خط لوله ناموفق بود', detail: describeError(error) })
    settle('error')
  }
}

export async function retryRun(runId: string) {
  const run = await api.advanceRun(runId).catch((e) => { store().toast({ tone: 'error', title: 'تلاش دوباره ناموفق بود', detail: describeError(e) }) })
  if (run) {
    store().setRun(run)
    if (run.status === 'committed') onCommitted(run)
  }
}

export async function abandonRun(runId: string) {
  const a = store()
  try {
    const run = await api.abandonRun(runId)
    a.setRun(run)
    if (a.conversationRun === runId) a.set({ conversationRun: null })
    a.log({ kind: 'abandoned', text: 'ثبت مطلب متوقف شد — چیزی نوشته نشد', refs: [runId] })
    a.toast({ tone: 'info', title: 'ثبت متوقف شد', detail: 'چیزی در آرشیو نوشته نشد.' })
    settle('idle')
  } catch (error) {
    a.toast({ tone: 'error', title: 'توقف ناموفق بود', detail: describeError(error) })
  }
}

export async function syncRun(runId: string) {
  const run = await api.run(runId).catch(() => null)
  if (run) store().setRun(run)
  return run
}

function onCommitted(run: EntryRun) {
  const a = store()
  if (!run.entry_id || a.committed[run.id]) return
  a.set({ committed: { ...a.committed, [run.id]: { entryId: run.entry_id, at: new Date().toISOString() } } })
  a.log({ kind: 'committed', text: `مدخل در آرشیو ثبت شد — ${run.entry_id.slice(0, 8)}`, refs: [run.entry_id] })
  a.toast({ tone: 'success', title: 'مدخل در آرشیو ثبت شد', detail: 'پرونده، اشخاص، استنادها و گراف همگام شدند.', undo: () => undoCommit(run.id) })
  void refreshArchive()
}

/** Undo a filing made in this session: delete the entry and the document it created. */
export async function undoCommit(runId: string) {
  const a = store()
  const c = a.committed[runId]
  if (!c || c.undone) return
  try {
    await api.deleteEntry(c.entryId, true)
    a.set({ committed: { ...a.committed, [runId]: { ...c, undone: true } } })
    a.log({ kind: 'undone', text: 'ثبت برگردانده شد — مدخل و سند آن حذف شدند', refs: [c.entryId] })
    a.toast({ tone: 'info', title: 'ثبت برگردانده شد', detail: 'مدخل و سند ساخته‌شده حذف شدند.' })
    void refreshArchive()
  } catch (error) {
    a.toast({ tone: 'error', title: 'برگرداندن ناموفق بود', detail: describeError(error) })
  }
}
