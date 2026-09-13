import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Intent, RunMode } from '@/api/types'

/**
 * The Streamlit left panel, as persistent client settings: the active model
 * and its knobs, the retrieval dials, speech-to-text, and the two per-message
 * choices beside the composer («نوع پیام», «حالت ثبت مدخل»).
 */
export interface RetrievalSettings {
  hybrid: boolean
  candidates: number
  rerank: boolean
  rerank_top: number
  rerank_model: string | null
}

interface SettingsState {
  modelId: string | null
  knobs: Record<string, string | number | boolean>
  topK: number
  retrieval: RetrievalSettings
  sttChoice: string | null
  intent: Intent | 'auto'
  runMode: RunMode
  speakReplies: boolean
  set: (patch: Partial<Omit<SettingsState, 'set' | 'setKnob' | 'setRetrieval'>>) => void
  setKnob: (key: string, value: string | number | boolean) => void
  setRetrieval: (patch: Partial<RetrievalSettings>) => void
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      modelId: null,
      knobs: {},
      topK: 5,
      retrieval: { hybrid: true, candidates: 30, rerank: false, rerank_top: 12, rerank_model: null },
      sttChoice: null,
      intent: 'auto',
      runMode: 'review',
      speakReplies: false,
      set: (patch) => set(patch),
      setKnob: (key, value) => set((s) => ({ knobs: { ...s.knobs, [key]: value } })),
      setRetrieval: (patch) => set((s) => ({ retrieval: { ...s.retrieval, ...patch } })),
    }),
    { name: 'legal.settings' },
  ),
)

/** What a request should carry: the model id, max_tokens and the other knobs, the retrieval overrides. */
export function requestSettings() {
  const s = useSettings.getState()
  const { max_tokens, ...knobs } = s.knobs
  return {
    model: s.modelId ?? undefined,
    max_tokens: typeof max_tokens === 'number' ? max_tokens : 1024,
    knobs,
    top_k: s.topK,
    retrieval: { hybrid: s.retrieval.hybrid, candidates: s.retrieval.candidates, rerank: s.retrieval.rerank, rerank_top: s.retrieval.rerank_top, ...(s.retrieval.rerank_model ? { rerank_model: s.retrieval.rerank_model } : {}) },
  }
}
