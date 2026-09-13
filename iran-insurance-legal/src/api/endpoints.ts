import { requestSettings } from '@/state/settings'
import { del, get, patch, post, qs, request } from './client'
import type {
  AnswerResult, ArchiveDocument, ArchiveState, CaseEntry, EntitySummary, EntryRun, Graph, Health, Intent, Label,
  LawArticle, LawTitle, LegalCaseDetail, LegalCaseRecord, ModelEntry, Options, RetrieveResult, RunMode, RunReply, SimilarCase,
} from './types'

/**
 * Every call the front end makes. The FastAPI engine is the authoritative
 * store — nothing here writes anything the user has not confirmed in the UI.
 */
export const api = {
  health: () => get<Health>('/health', 5000),
  state: () => get<ArchiveState>('/legal/api/state'),
  options: () => get<Options>('/legal/api/options'),
  models: () => get<{ current: string; models: ModelEntry[] }>('/models', 30_000),

  // ---- the assistant
  route: (text: string) => post<{ intent: Intent; confidence: number; clarification: string; reason: string; label: string }>('/legal/api/route', { text, model: requestSettings().model }),
  command: (text: string) => post<{ command: string | null }>('/legal/api/command', { text }),
  ask: (question: string, extra: { document_ids?: string[]; collection?: string | null; filters?: Record<string, string> } = {}) => {
    const s = requestSettings()
    return post<AnswerResult>('/legal/api/ask', {
      question, top_k: s.top_k, model: s.model, max_tokens: s.max_tokens, knobs: s.knobs,
      collection: extra.collection || undefined, filters: extra.filters,
      retrieval: { ...s.retrieval, ...(extra.document_ids ? { document_ids: extra.document_ids } : {}) },
    }, 180_000)
  },
  assistant: (text: string, intent: Intent) => post<AnswerResult>('/assistant', { text, intent, model: requestSettings().model }, 180_000),
  answers: (limit = 50) => get<{ answers: Record<string, unknown>[] }>(`/answers${qs({ limit })}`),

  // ---- the entry pipeline (human-gated)
  startRun: (text: string, mode: RunMode, source?: string) => post<RunReply>('/runs', { text, mode, source, model: requestSettings().model }, 240_000),
  replyRun: (id: string, text: string) => post<RunReply>(`/runs/${id}/reply`, { text, model: requestSettings().model }, 240_000),
  advanceRun: (id: string, patchBody?: Record<string, unknown>) => post<EntryRun>(`/legal/api/runs/${id}/advance`, { patch: patchBody ?? null, model: requestSettings().model }, 240_000),
  abandonRun: (id: string) => post<EntryRun>(`/legal/api/runs/${id}/abandon`),
  run: (id: string) => get<EntryRun>(`/runs/${id}`),
  runs: (limit = 50) => get<{ runs: EntryRun[] }>(`/runs${qs({ limit })}`),

  // ---- extraction preview (section ۰۵) and plain ingest
  extractPreview: (text: string) => post<{ intent: 'archive'; draft: Record<string, unknown>; related: { document_id: string; title: string; similarity?: number }[]; raw_text: string }>('/assistant', { text, intent: 'archive', model: requestSettings().model }, 180_000),
  commitDraft: (draft: Record<string, unknown>, raw_text: string, source: string) => post<{ id: string; title: string; document_id: string | null }>('/assistant/commit', { draft, raw_text, source }),
  ingest: (documents: { text: string; source: string; title?: string; metadata?: Record<string, unknown> }[], extract = true) =>
    post<{ results: { source: string; status: string; chunks: number }[]; indexed_chunks: number }>('/ingest', { documents, extract }, 300_000),

  // ---- documents
  documents: (p: { q?: string; limit?: number; offset?: number; collection?: string; year?: string; group?: string; doc_kind?: string; status?: string; tag?: string }) =>
    get<{ total: number; items: ArchiveDocument[] }>(`/documents${qs(p)}`),
  document: (id: string) => get<ArchiveDocument & { raw_text: string; chunks: { id?: string; chunk_index: number; text: string }[] }>(`/documents/${id}`),
  patchDocumentMeta: (id: string, body: { status?: string; add_tags?: string[]; remove_tags?: string[]; set?: Record<string, unknown> }) => patch<{ id: string; metadata: Record<string, unknown> }>(`/documents/${id}/meta`, body),
  deleteDocument: (id: string) => del<{ deleted: string }>(`/documents/${id}`),

  // ---- retrieval
  retrieve: (query: string, overrides: { top_k?: number; rerank?: boolean; collection?: string | null; filters?: Record<string, string> } = {}) => {
    const s = requestSettings()
    return post<RetrieveResult>('/legal/api/retrieve', {
      query, top_k: overrides.top_k ?? s.top_k, collection: overrides.collection || undefined, filters: overrides.filters,
      retrieval: { ...s.retrieval, ...(overrides.rerank !== undefined ? { rerank: overrides.rerank } : {}) },
    }, 120_000)
  },

  // ---- entries (editor, review)
  entry: (id: string) => get<CaseEntry>(`/entries/${id}`),
  patchEntry: (id: string, body: Record<string, unknown>) => patch<CaseEntry>(`/entries/${id}`, body),
  deleteEntry: (id: string, withDocument = false) => del<{ deleted: string }>(`/entries/${id}${qs({ with_document: withDocument })}`),

  // ---- cases
  cases: (p: { case_type?: string; insurance_line?: string; status?: string; court?: string; q?: string } = {}) => get<{ items: LegalCaseRecord[] }>(`/cases${qs(p)}`),
  caseDetail: (id: string) => get<LegalCaseDetail>(`/cases/${encodeURIComponent(id)}`),
  patchCase: (id: string, body: Record<string, unknown>) => patch<LegalCaseRecord>(`/cases/${encodeURIComponent(id)}`, body),
  similarCases: (id: string) => get<{ case: { id: string; case_number: string; title: string }; similar: SimilarCase[]; lessons: unknown }>(`/cases/${encodeURIComponent(id)}/similar`),
  caseGraph: (id: string, depth = 1) => get<Graph>(`/cases/${encodeURIComponent(id)}/graph${qs({ depth })}`),
  addCaseEvent: (caseId: string, body: { date: string; title: string; detail?: string; reminder?: boolean }) => post<Record<string, unknown>>(`/legal/api/cases/${encodeURIComponent(caseId)}/events`, body),
  resync: () => post<{ entries: number }>('/archive/resync'),

  // ---- laws, entities, graph
  laws: (p: { law_title?: string; q?: string } = {}) => get<{ titles?: LawTitle[]; items: LawArticle[] }>(`/laws${qs(p)}`),
  law: (id: string) => get<LawArticle>(`/laws/${id}`),
  addLaw: (body: { law_title: string; article_no?: string; text: string; kind?: string; law_year?: string; title?: string; keywords?: string[] }) => post<LawArticle>('/laws', body),
  entities: (kind: 'person' | 'org', q?: string) => get<{ items: EntitySummary[] }>(`/entities/${kind}${qs({ q, limit: 300 })}`),
  entity: (kind: 'person' | 'org', key: string) => get<Record<string, unknown>>(`/entities/${kind}/${encodeURIComponent(key)}`),
  graph: (type: string, id: string, depth = 1) => get<Graph>(`/graph/${type}/${encodeURIComponent(id)}${qs({ depth })}`),
  vault: () => get<{ nodes: { id: string; label?: string; type?: string; uri?: string; [k: string]: unknown }[]; edges: { source?: string; target?: string; src?: string; dst?: string }[]; tags: unknown; vault: string; exported: boolean }>('/graph/vault'),
  exportVault: () => post<Record<string, unknown>>('/graph/vault/export', undefined, 300_000),

  // ---- labels & evaluation
  labels: (p: { kind?: string; target_type?: string; target_id?: string; limit?: number } = {}) => get<Label[]>(`/labels${qs(p)}`),
  addLabel: (body: { kind: 'relevance' | 'tag' | 'review'; target_type: 'chunk' | 'document' | 'entry'; target_id: string; value?: string | null; query?: string | null; note?: string | null }) => post<{ id: string }>('/labels', { ...body, labeled_by: 'web' }),
  deleteLabel: (id: string) => del<{ deleted: string }>(`/labels/${id}`),
  labelsSummary: () => get<{ by_kind: Record<string, number>; relevance_queries: number; eval_ready_queries: number; documents_tagged: number }>('/labels/summary'),
  stats: () => get<Record<string, unknown>>('/stats'),
  schema: () => get<Record<string, unknown>>('/schema'),
  evalFiles: () => get<{ files: string[] }>('/legal/api/eval/files'),
  evaluate: (body: { path: string; top_k: number; rerank?: boolean }) => {
    const s = requestSettings()
    return post<Record<string, unknown>>('/legal/api/eval', { path: body.path, top_k: body.top_k, retrieval: { ...s.retrieval, ...(body.rerank !== undefined ? { rerank: body.rerank } : {}) } }, 600_000)
  },
  bench: (questions: string[], model_ids: string[], top_k: number) => post<Record<string, unknown>>('/bench', { questions, model_ids, top_k }, 600_000),

  // ---- integrations
  integrations: () => get<{ ci_runs: Record<string, unknown>[]; hooks: Record<string, number> }>('/legal/api/integrations'),
  hooks: () => get<{ hooks: Record<string, unknown>[]; events: string[] }>('/hooks'),
  addHook: (body: { url: string; events: string[]; description?: string }) => post<Record<string, unknown>>('/hooks', body),
  deleteHook: (id: string) => del<Record<string, unknown>>(`/hooks/${id}`),
  testHook: (id: string) => post<Record<string, unknown>>(`/hooks/${id}/test`),
  deliveries: () => get<{ deliveries: Record<string, unknown>[] }>('/hooks/deliveries'),
  drainHooks: () => post<{ tried: number }>('/legal/api/hooks/drain'),
  ciEvents: () => get<{ runs: Record<string, unknown>[] }>('/ci/events'),
  demoStages: () => get<{ stages: { id: string; title: string; blurb: string; prompts: { text: string; intent: Intent | null; mode: RunMode | null; note?: string; reply?: boolean }[]; show: string[] }[] }>('/legal/api/demo/stages'),

  // ---- speech
  transcribe: (audio: Blob, choice?: string | null) => {
    const form = new FormData()
    form.append('file', audio, 'voice.webm')
    return request<{ text?: string }>(`/legal/api/transcribe${qs({ choice })}`, { method: 'POST', body: form, timeout: 90_000 })
  },
}
