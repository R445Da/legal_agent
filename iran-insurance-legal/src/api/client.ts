import { useConnection } from '@/state/connection'

export class ApiError extends Error {
  constructor(readonly status: number, readonly detail: string) {
    super(detail || `HTTP ${status}`)
  }
}

/** Human-readable Persian message for a failed call. */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) return 'مدل زبانی در دسترس نیست — از «تنظیمات» مدل دیگری انتخاب کنید.'
    if (error.status === 401) return 'توکن دسترسی نامعتبر است — آن را در «تنظیمات › اتصال» وارد کنید.'
    if (error.status === 404) return `یافت نشد — ${error.detail}`
    return `خطای سرور (${error.status}) — ${error.detail}`
  }
  if (error instanceof DOMException && error.name === 'AbortError') return 'زمان پاسخ‌گویی سرور به پایان رسید.'
  if (error instanceof TypeError) return 'اتصال به سرور برقرار نشد — آیا API در حال اجراست؟ (scripts/legal-web.sh)'
  return error instanceof Error ? error.message : String(error)
}

export async function request<T>(path: string, init: RequestInit & { timeout?: number } = {}): Promise<T> {
  const { baseUrl, token } = useConnection.getState()
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), init.timeout ?? 120_000)
  try {
    const isForm = init.body instanceof FormData
    const res = await fetch(`${baseUrl.replace(/\/$/, '')}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        ...(init.body && !isForm ? { 'content-type': 'application/json' } : {}),
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    })
    if (!res.ok) {
      let detail = ''
      try {
        const body = await res.json()
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
      } catch {
        detail = await res.text().catch(() => '')
      }
      throw new ApiError(res.status, detail.slice(0, 400))
    }
    const type = res.headers.get('content-type') ?? ''
    return (type.includes('json') ? await res.json() : await res.text()) as T
  } finally {
    clearTimeout(timer)
  }
}

export const get = <T,>(path: string, timeout?: number) => request<T>(path, { timeout })
export const post = <T,>(path: string, body?: unknown, timeout?: number) => request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body), timeout })
export const patch = <T,>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = <T,>(path: string) => request<T>(path, { method: 'DELETE' })

export const qs = (params: Record<string, string | number | boolean | undefined | null>) => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : ''
}
