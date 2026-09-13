import type { ArchiveState, SectionId } from '@/api/types'
import { SECTIONS } from '@/sections/registry'

/**
 * Navigation only. Everything that is a *question or a filing* goes to the
 * engine's router (`orchestrator.route` via /legal/api/route) — this parser
 * just recognises explicit requests to open a section or a known record, in
 * Persian or English, so "open cases" does not cost a model call.
 */
export interface Navigation {
  section: SectionId
  tab?: string
  record?: string
  label?: string
  reply: string
  why: string[]
}

const fold = (s: string) => s
  .replace(/[يى]/g, 'ی').replace(/ك/g, 'ک').replace(/[ۀة]/g, 'ه').replace(/‌/g, ' ')
  .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d))).replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
  .toLowerCase().replace(/\s+/g, ' ').trim()

const OPEN = /^(?:(?:لطفا|لطفاً)\s+)?(?:باز کن|بازکن|نشان بده|نمایش بده|نمایش|برو به|ببر به|بیا|open|show|go to|take me to)\b|(?:را|رو)?\s*(?:باز کن|نشان بده|نمایش بده|بیاور)$/

const WORDS: [RegExp, SectionId, string?][] = [
  [/داشبورد|dashboard|نمای کلی/, 'dashboard'],
  [/صف بازبینی|بازبینی انسانی|پرونده(?: ها)? ناقص|review queue/, 'review'],
  [/پرونده(?: ها)?(?: جاری| باز)|open cases/, 'cases', 'open'],
  [/پرونده(?: ها)? مختومه|closed cases/, 'cases', 'closed'],
  [/پرونده ها|پرونده‌ها|cases\b/, 'cases'],
  [/رویداد|تقویم|خط زمان|events|timeline/, 'events'],
  [/اسناد|تیکت|documents|tickets/, 'documents'],
  [/قوانین|مستندات قانونی|laws\b/, 'laws'],
  [/اشخاص|سازمان ها|entities|people/, 'entities'],
  [/نقشه دانش|گراف|graph|knowledge map/, 'graphmap'],
  [/سند جدید|بایگانی سند|ingest|upload/, 'ingest'],
  [/ویرایش مدخل|ویرایشگر|editor/, 'editor'],
  [/طبقه بندی|برچسب ها|taxonomy|tags/, 'taxonomy'],
  [/برچسب گذاری|بازخورد|labeling/, 'labeling'],
  [/جستجو و پرسش|آزمایشگاه بازیابی|search/, 'search'],
  [/آمار|analytics|statistics/, 'analytics'],
  [/ارزیابی|eval/, 'eval'],
  [/مقایسه مدل|bench/, 'bench'],
  [/ساختار داده|خط لوله|schema|pipeline/, 'schema'],
  [/نمایشگاه|گالری|gallery/, 'gallery'],
  [/وب هوک|webhook|\bci\b/, 'webhooks'],
  [/تنظیمات|settings/, 'settings'],
]

export function parseNavigation(text: string, state?: ArchiveState): Navigation | null {
  const t = fold(text)
  if (!t) return null
  const explicit = OPEN.test(t)
  const short = t.split(' ').length <= 4

  // A bare case number, or "open case 1404705025".
  const num = t.match(/\b(\d{6,})\b/)?.[1]
  if (num && state && (explicit || short || /پرونده|case/.test(t))) {
    const c = state.cases.find((x) => fold(x.number ?? '') === num)
    if (c && (explicit || t.replace(/[^\d]/g, '') === num || short)) {
      return { section: 'cases', record: c.id, label: c.number, reply: `پروندهٔ ${c.number} را باز کردم.`, why: [`شمارهٔ پرونده «${c.number}» در متن شما`] }
    }
  }

  if (!explicit && !short) return null
  // Questions go to the router, not here.
  if (/[؟?]|چه |چرا|چگونه|کدام|آیا|چند |how|what|which|why/.test(t)) return null

  for (const [re, section, tab] of WORDS) {
    if (re.test(t)) {
      const def = SECTIONS.find((s) => s.id === section)!
      return { section, tab, reply: `«${def.num} ${def.title}» را باز کردم.`, why: [explicit ? 'درخواست صریح برای باز کردن بخش' : 'نام بخش در پیام کوتاه شما', `«${def.title}»`] }
    }
  }
  return null
}
