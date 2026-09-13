/**
 * The legal assistant's data, as the FastAPI engine returns it. These mirror
 * `app/rag/catalog.py`, `cases.py`, `casebase.py`, `lawbase.py`, `runs.py` and
 * the /assistant result shapes. Extracted fields are model output, so text
 * fields are typed loosely where the engine itself normalises them.
 */

export type SectionId =
  | 'dashboard' | 'cases' | 'events' | 'ingest' | 'search' | 'documents' | 'taxonomy'
  | 'review' | 'labeling' | 'analytics' | 'schema' | 'eval' | 'bench' | 'laws'
  | 'entities' | 'editor' | 'gallery' | 'webhooks' | 'graphmap' | 'settings'

export type Intent = 'query' | 'law' | 'cases' | 'agent' | 'archive' | 'analytics' | 'chat' | 'unclear'
export type RunMode = 'conversation' | 'review' | 'steps' | 'auto'

export interface Party { name: string; role: string }
export interface Representation { lawyer?: string; client?: string; for?: string; party?: string }
export interface CaseEvent { date?: string; description?: string; what?: string; type?: string; detail?: string; source?: string; reminder?: boolean }
export interface EntryLegalRef { law?: string; article?: string; context?: string; used_by?: string; ref_id?: string | null; resolved?: boolean; text?: string; keep?: boolean }

export interface EntryEntities {
  case_number?: string; court?: string; topic?: string | string[]; people?: string[]; orgs?: string[]
  case_type?: string; insurance_line?: string; claim_amount?: string | number; outcome?: string
  status?: string; filed_date?: string; stage?: string; group?: string; branch?: string
  [key: string]: unknown
}

export interface CaseEntry {
  id: string
  document_id: string | null
  kind: string
  title: string
  summary: string
  entities: EntryEntities
  parties: (Party | string)[]
  events: (CaseEvent | string)[]
  representation: Representation[]
  tags: string[]
  related_ids: string[]
  related: RelatedLink[]
  legal_refs: EntryLegalRef[]
  case_id: string | null
  raw_text?: string
  created_at: string | null
}

export interface RelatedLink { entry_id?: string | null; document_id?: string | null; title: string; score?: number | null; outcome?: string; why?: string; keep?: boolean }

/** The relational case row (`legal_cases`). */
export interface LegalCaseRecord {
  id: string
  case_number: string
  title: string
  case_type: string | null
  insurance_line: string | null
  court: string | null
  branch: string | null
  group: string | null
  status: string | null
  status_fa: string | null
  stage: string | null
  filed_date: string | null
  decided_date: string | null
  outcome: string | null
  claim_amount: number | null
  summary: string | null
  created_at?: string
  updated_at?: string
}

export interface CaseReference {
  id: string; kind: string; kind_fa: string; law_title: string; law_year: string | null; article_no: string | null
  title: string | null; text: string; keywords: string[]; cite: string; context?: string; used_by?: string; weight?: number
}
export interface CaseRecordParty { id: string; name: string; role: string; role_fa: string; type: 'person' | 'org' }
export interface LegalCaseDetail extends LegalCaseRecord { parties: CaseRecordParty[]; references: CaseReference[]; entries: CaseEntry[]; events: CaseEvent[] }

/** A case as the case views see it: entries folded by case number (`cases.derive_cases`). */
export interface LegalCase {
  id: string
  number: string
  title: string
  subject: string
  court: string
  entries: CaseEntry[]
  parties: Party[]
  representation: Representation[]
  events: (CaseEvent & { entry_id?: string })[]
  topics: string[]
  tags: string[]
  related_ids: string[]
  related_links: RelatedLink[]
  doc_ids: string[]
  incomplete: boolean
  incomplete_reasons: string[]
  last_event_date: string | null
  text: string
  record: LegalCaseRecord | null
}

export interface ArchiveEvent extends CaseEvent { entry_id?: string; case_id: string; case_title: string; case_number: string }
export interface TagCount { tag: string; cases: number }
export interface NamedCount { name: string; count: number }

export interface ArchiveStats {
  cases: number; persons: number; orgs: number; laws: number; citations: number
  claim_total: number; claim_avg: number
  by_type: NamedCount[]; by_line?: NamedCount[]; by_status?: NamedCount[]; by_court?: NamedCount[]
  top_laws?: { cite?: string; name?: string; count: number; id?: string }[]
  [key: string]: unknown
}

export interface LawTitle { law_title: string; kind: string; law_year: string | null; articles: number }
export interface Taxonomy { root: string; categories: { name: string; leaves: string[] }[] }

export interface SchemaOverview {
  model: { name: string; fa: string; what: string; count: number; fields: string[] }[]
  entry_form: { title: string; fields: { key: string; label: string; type: string; help: string; options?: string[]; roles?: Record<string, string> }[] }
  pipeline: Record<string, string[]>
  pipeline_note: string
}

export interface ArchiveState {
  entries: CaseEntry[]
  counts: { documents: number; chunks: number; entries: number }
  collections: { name: string; documents: number }[]
  facets: Record<string, { value: string; documents: number }[]>
  schema: SchemaOverview
  legal_cases: LegalCaseRecord[]
  law_titles: LawTitle[]
  archive: ArchiveStats
  cases: LegalCase[]
  events: ArchiveEvent[]
  tags: TagCount[]
  review_queue: LegalCase[]
  taxonomy: Taxonomy[]
}

export interface Knob { key: string; label: string; kind: 'select' | 'slider' | 'toggle'; default: string | number | boolean; options: string[]; min?: number; max?: number; step?: number; help: string }
export interface ModelEntry { id: string; label: string; provider: string; model: string; available: boolean; reason: string; reasoning: boolean; knobs: Knob[]; chain?: string[] }

export interface Options {
  intents: Record<Intent, string>
  run_modes: { id: RunMode; label: string }[]
  steps: { id: string; label: string; gate: boolean }[]
  case_types: string[]
  insurance_lines: string[]
  taxonomy_leaves: string[]
  retrieval: { hybrid: boolean; rerank: boolean; embedding_model: string; rerank_model: string; candidates_per_side: number; rerank_top: number; rrf_lex_weight: number }
  rerank: { enabled: boolean; default: string; choices: { id: string; label: string }[] }
  stt: { enabled: boolean; default: string | null; choices: { id: string; label: string }[] }
}

export interface Health {
  status: string; llm_provider?: string; llm_model?: string | null; llm_available?: boolean
  indexed_documents?: number; indexed_chunks?: number; auth_required?: boolean; embedding_model?: string; stt_available?: boolean
}

export interface Context { n: number; document_id?: string | null; chunk_id?: string | null; title?: string | null; source?: string; chunk_index?: number; similarity?: number | null; text: string }
export interface Step { name: string; detail?: string; ms?: number }

export interface EvidenceItem { n: number; kind: string; id?: string; cite?: string; title?: string; score?: number | null; label?: string }
export interface Provenance { version: number; intent: string; provider: string; model: string; evidence: EvidenceItem[]; [key: string]: unknown }

export interface SimilarCase extends LegalCaseRecord { score?: number; reasons?: string[]; why?: string[]; path?: unknown }

/** Everything /assistant and /legal/api/ask can return, by intent. */
export interface AnswerResult {
  intent: Intent
  answer?: string
  summary?: string
  clarification?: string
  contexts?: Context[]
  refs?: CaseReference[]
  cases?: LegalCaseRecord[]
  similar_cases?: SimilarCase[]
  lessons?: string[] | string
  advice?: string
  stats?: Record<string, unknown>
  provenance?: Provenance
  answer_id?: string
  model?: string | null
  latency_ms?: number | null
  steps?: Step[]
  retrieval?: Record<string, number>
  /** An agent answer's edit proposal (`app/rag/entryedit.py`) — written by nothing until confirmed. */
  pending_edit?: EditProposal | null
}

/** The current value beside the new one. Only `/entries/{id}/apply` commits it. */
export interface EditProposal {
  entry_id: string
  entry_title: string
  field: string
  facet: string | null
  field_fa: string
  old: unknown
  old_text: string
  new: unknown
  new_text: string
  patch: Record<string, unknown>
  op: 'edit' | 'append'
}

export type FocusKind = 'entry' | 'case' | 'document' | 'person' | 'org'
export interface ConversationFocus { kind?: FocusKind; id?: string; label?: string }

/** A persisted chat thread (`app/rag/conversations.py`). */
export interface ConversationSummary {
  id: string
  title: string
  source: string
  focus: ConversationFocus
  created_at: string | null
  updated_at: string | null
  /** The list endpoint returns a count; the detail endpoint returns the turns. */
  messages: number
}
export interface ConversationTurn { id: string; role: 'user' | 'assistant'; text: string; intent: string | null; model: string | null; created_at: string | null; [extra: string]: unknown }
export interface ConversationDetail extends Omit<ConversationSummary, 'messages'> { messages: ConversationTurn[] }

export type RunStepStatus = 'pending' | 'running' | 'done' | 'failed' | 'awaiting_input' | 'skipped'
export interface RunStep { seq: number; step_id: string; label: string; status: RunStepStatus; detail: string | null; payload: Record<string, unknown>; error: string | null; ms: number | null; created_at: string | null }
export interface EntryRun {
  id: string; kind: string; status: 'running' | 'awaiting_input' | 'committed' | 'failed' | 'abandoned' | string
  raw_text: string; source: string | null; state: Record<string, unknown>; entry_id: string | null
  created_at: string | null; updated_at: string | null; steps: RunStep[]
}
export interface RunReply { intent?: 'archive'; run: EntryRun; waiting: boolean; message: string | null }

export interface ArchiveDocument { id: string; source: string; title: string | null; metadata?: Record<string, unknown>; doc_metadata?: Record<string, unknown>; chunks?: number | { id: string; chunk_index: number; text: string }[]; created_at?: string; raw_text?: string; [key: string]: unknown }

export interface Label { id: string; kind: 'relevance' | 'tag' | 'review'; target_type: string; target_id: string; value: string | null; query: string | null; note: string | null; created_at: string | null }

export interface LawArticle { id: string; kind: string; kind_fa: string; law_title: string; law_year: string | null; article_no: string | null; title: string | null; text: string; keywords: string[]; cite?: string; cited_by?: { id: string; label: string; type: string }[] }

export interface EntitySummary { id: string; name: string; roles: string[]; roles_fa: string[]; kind: string | null; cases: number }

export interface GraphNode { id: string; type: string; label: string; [key: string]: unknown }
export interface GraphEdge { src: string; dst: string; rel: string; [key: string]: unknown }
export interface Graph { nodes: GraphNode[]; edges: GraphEdge[] }

export interface RetrieveHit { n: number; chunk_id: string; document_id: string; title: string; source: string; chunk_index: number; similarity: number; text: string }
export interface RetrieveResult { query: string; hits: RetrieveHit[]; entries: CaseEntry[]; trace: Record<string, number>; config: Record<string, unknown> }
