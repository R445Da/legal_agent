import { create } from 'zustand'
import type { Health } from '@/api/types'

/** Last known server status (kept in sync by the health poll in App). */
interface BackendState {
  health: Health | null
  error: string | null
  set: (patch: Partial<Pick<BackendState, 'health' | 'error'>>) => void
}

export const useBackend = create<BackendState>((set) => ({ health: null, error: null, set: (patch) => set(patch) }))
