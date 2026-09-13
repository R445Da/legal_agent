import type { AnswerResult, Intent, SectionId } from '@/api/types'
import type { WorkspaceContext } from '@/state/context'

/**
 * What the conversation holds. An answer is shown with its evidence; a filing
 * is an entry run whose gates are the human approval checkpoints. Nothing
 * here is authoritative — the archive is the API's database.
 */
export type OrbState = 'idle' | 'listening' | 'processing' | 'working' | 'responding' | 'awaiting' | 'completed' | 'error'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  at: string
  text: string
  streaming?: boolean
  intent?: Intent
  intentLabel?: string
  /** «پرسش از این پرونده» — the answer came from one case's documents only. */
  scope?: string
  result?: AnswerResult
  runId?: string
  clarify?: { original: string; options: Intent[] }
  error?: string
  retry?: { text: string; intent?: Intent }
  context?: WorkspaceContext
  route?: { section: SectionId; tab?: string; record?: string; label: string }
  why?: string[]
  /** What became of `result.pending_edit` — set by the edit gate. */
  editState?: 'done' | 'cancelled'
  /** On the turn that records a gate's outcome: the message whose proposal it settled. */
  editOf?: string
  editOutcome?: 'done' | 'cancelled'
  /** Reopened from the server. A proposal on such a turn is shown, never applied — the record may have changed since. */
  restored?: boolean
}

export type ActivityKind = 'routed' | 'answered' | 'filing' | 'gate' | 'committed' | 'abandoned' | 'undone' | 'failed' | 'saved' | 'deleted' | 'edited'
export interface Activity { id: string; at: string; kind: ActivityKind; text: string; refs: string[] }

export interface Toast { id: string; tone: 'success' | 'error' | 'info'; title: string; detail?: string; undo?: () => Promise<void> | void }
