import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useConnection } from '@/state/connection'
import { api } from './endpoints'

/**
 * Read hooks. `['state']` is the archive bundle every case-oriented section
 * reads (the Streamlit `data.load()`); `refreshArchive()` is its `refresh()`.
 */
const conn = () => { const c = useConnection.getState(); return `${c.baseUrl}|${c.token}` }

export const archiveKey = () => ['state', conn()]
export const useArchive = () => useQuery({ queryKey: archiveKey(), queryFn: api.state, staleTime: 60_000 })
export const useOptions = () => useQuery({ queryKey: ['options', conn()], queryFn: api.options, staleTime: 10 * 60_000 })
export const useModels = () => useQuery({ queryKey: ['models', conn()], queryFn: api.models, staleTime: 10 * 60_000 })
export const useHealth = () => {
  useConnection((s) => s.baseUrl + s.token)
  return useQuery({ queryKey: ['health', conn()], queryFn: api.health, refetchInterval: 20_000, retry: false })
}

export function useRefreshArchive() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ predicate: (q) => !['options', 'models', 'health'].includes(String(q.queryKey[0])) })
}
