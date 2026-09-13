import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

let counter = 0
export function uid(prefix: string) {
  counter = (counter + 1) % 1_000_000
  return `${prefix}_${Date.now().toString(36)}${counter.toString(36)}`
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** Extraction is model output: fields typed as strings arrive as lists and vice versa. */
export function asText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(asText).filter(Boolean).join('، ')
  if (typeof value === 'object') return Object.values(value as Record<string, unknown>).map(asText).filter(Boolean).join(' — ')
  return String(value).trim()
}
