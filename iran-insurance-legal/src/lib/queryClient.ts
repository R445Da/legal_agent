import { QueryClient, keepPreviousData } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, placeholderData: keepPreviousData, refetchOnWindowFocus: false, retry: 1 } },
})
