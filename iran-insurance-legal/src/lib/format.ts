/**
 * Persian formatting. The Streamlit UI's rule holds here too: Latin digits
 * in the interface are a bug — every number goes through `fa()`.
 */

const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹'
const nf = new Intl.NumberFormat('fa-IR')

/** Number → Persian digits with Persian grouping; strings get their digits replaced. */
export function fa(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return Number.isFinite(value) ? nf.format(value) : '—'
  return value.replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)])
}

export const pct = (ratio: number, digits = 0) => `${fa(Number((ratio * 100).toFixed(digits)))}٪`
export const ms = (value?: number | null) => (value == null ? '—' : value >= 1000 ? `${fa(Number((value / 1000).toFixed(1)))} ثانیه` : `${fa(Math.round(value))} میلی‌ثانیه`)

/** Rial amounts as the Streamlit case view shows them. */
export function rial(amount?: number | string | null) {
  if (amount === null || amount === undefined || amount === '' || amount === 0) return '—'
  const n = typeof amount === 'string' ? Number(amount.replace(/[^\d]/g, '')) : amount
  return Number.isFinite(n) ? `${nf.format(n)} ریال` : fa(String(amount))
}

export function compactRial(amount?: number | null) {
  if (!amount) return '—'
  if (amount >= 1e12) return `${fa(Number((amount / 1e12).toFixed(1)))} هزار میلیارد ریال`
  if (amount >= 1e9) return `${fa(Number((amount / 1e9).toFixed(1)))} میلیارد ریال`
  if (amount >= 1e6) return `${fa(Number((amount / 1e6).toFixed(1)))} میلیون ریال`
  return rial(amount)
}

const dateFmt = new Intl.DateTimeFormat('fa-IR-u-ca-persian', { year: 'numeric', month: 'long', day: 'numeric' })
const timeFmt = new Intl.DateTimeFormat('fa-IR', { hour: '2-digit', minute: '2-digit' })
/** ISO timestamp → Solar Hijri date. Dates already written in Persian (۱۴۰۲/۰۵/۱۲) pass through. */
export function date(value?: string | null) {
  if (!value) return '—'
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? fa(value) : dateFmt.format(d)
  }
  return fa(value)
}
export const time = (iso: string) => timeFmt.format(new Date(iso))

export function ago(iso: string) {
  const s = Math.round((Date.now() - Date.parse(iso)) / 1000)
  if (s < 45) return 'همین حالا'
  if (s < 3600) return `${fa(Math.round(s / 60))} دقیقه پیش`
  if (s < 86400) return `${fa(Math.round(s / 3600))} ساعت پیش`
  return `${fa(Math.round(s / 86400))} روز پیش`
}

export const plural = (n: number, noun: string) => `${fa(n)} ${noun}`
