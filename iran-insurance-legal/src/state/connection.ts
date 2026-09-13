import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Where the legal-assistant API (app/main.py) lives. Dev: the Vite proxy at
 * /api. Production: FastAPI serves this build at /legal/, so the API is
 * same-origin (''). The token is the server's API_TOKEN, when it sets one.
 */
export const defaultBase = () => (import.meta.env.DEV ? '/api' : '')

interface ConnectionState {
  baseUrl: string
  token: string
  set: (patch: Partial<Pick<ConnectionState, 'baseUrl' | 'token'>>) => void
}

export const useConnection = create<ConnectionState>()(
  persist((set) => ({ baseUrl: defaultBase(), token: '', set: (patch) => set(patch) }), { name: 'legal.connection' }),
)
