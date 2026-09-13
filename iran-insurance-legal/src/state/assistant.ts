import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { EntryRun } from '@/api/types'
import type { Activity, Message, OrbState, Toast } from '@/assistant/types'
import { uid } from '@/lib/utils'

export interface Banner { id: string; text: string; why: string[]; view: string }

interface AssistantState {
  orb: OrbState
  busy: boolean
  messages: Message[]
  runs: Record<string, EntryRun>
  /** A conversation-mode filing waiting for the user's next reply. */
  conversationRun: string | null
  /** Entries committed in this session, keyed by run — the undo window. */
  committed: Record<string, { entryId: string; at: string; undone?: boolean }>
  activity: Activity[]
  toasts: Toast[]
  banner: Banner | null

  setOrb: (orb: OrbState) => void
  setBusy: (busy: boolean) => void
  push: (m: Omit<Message, 'id' | 'at'>) => string
  patch: (id: string, patch: Partial<Message>) => void
  setRun: (run: EntryRun) => void
  set: (patch: Partial<Pick<AssistantState, 'conversationRun' | 'committed'>>) => void
  log: (a: Omit<Activity, 'id' | 'at'>) => void
  toast: (t: Omit<Toast, 'id'>) => void
  dismiss: (id: string) => void
  setBanner: (b: Omit<Banner, 'id'> | null) => void
  clear: () => void
}

export const useAssistant = create<AssistantState>()(
  persist(
    (set) => ({
      orb: 'idle',
      busy: false,
      messages: [],
      runs: {},
      conversationRun: null,
      committed: {},
      activity: [],
      toasts: [],
      banner: null,

      setOrb: (orb) => set({ orb }),
      setBusy: (busy) => set({ busy }),
      push: (m) => {
        const id = uid('msg')
        set((s) => ({ messages: [...s.messages, { ...m, id, at: new Date().toISOString() }].slice(-120) }))
        return id
      },
      patch: (id, patch) => set((s) => ({ messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)) })),
      setRun: (run) => set((s) => ({ runs: { ...s.runs, [run.id]: run } })),
      set: (patch) => set(patch),
      log: (a) => set((s) => ({ activity: [{ ...a, id: uid('act'), at: new Date().toISOString() }, ...s.activity].slice(0, 300) })),
      toast: (t) => set((s) => ({ toasts: [...s.toasts, { ...t, id: uid('toast') }].slice(-4) })),
      dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
      setBanner: (b) => set({ banner: b ? { ...b, id: uid('banner') } : null }),
      clear: () => set({ messages: [], conversationRun: null }),
    }),
    {
      name: 'legal.assistant',
      partialize: (s) => ({ messages: s.messages.map((m) => ({ ...m, streaming: false })), runs: s.runs, activity: s.activity, committed: s.committed, conversationRun: s.conversationRun }),
    },
  ),
)
