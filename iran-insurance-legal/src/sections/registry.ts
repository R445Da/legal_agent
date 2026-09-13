import {
  Archive, BookOpenText, CalendarClock, ChartColumnBig, ClipboardCheck, FilePlus2, FileText, FlaskConical, FolderKanban,
  Gauge, LayoutDashboard, Network, Palette, PenLine, Scale, Search, Settings2, Tags, ThumbsUp, Users, Webhook,
  type LucideIcon,
} from 'lucide-react'
import { fa } from '@/lib/format'
import type { ArchiveState, SectionId } from '@/api/types'

/**
 * The sections of the legal assistant — the Streamlit rail (۰۲–۲۰) plus its
 * left panel as «تنظیمات». ۰۱ «دستیار پرونده» is the AI home itself. Numbers
 * and Persian labels are how users refer to screens, so they match nav.py.
 */
export type Tone = 'indigo' | 'cyan' | 'amber' | 'violet' | 'emerald' | 'slate' | 'rose' | 'sky'

export interface SectionDef {
  id: SectionId
  num: string
  title: string
  group: GroupId
  description: string
  icon: LucideIcon
  tone: Tone
  tabs: { id: string; label: string }[]
  metric?: (s: ArchiveState) => { label: string; attention?: boolean }
}

export type GroupId = 'archive' | 'intake' | 'research' | 'lab' | 'system'
export const GROUPS: { id: GroupId; title: string; hint: string }[] = [
  { id: 'archive', title: 'بایگانی', hint: 'پرونده‌ها، اسناد، اشخاص و قوانین' },
  { id: 'intake', title: 'ثبت و کیفیت', hint: 'ورود مطلب، ویرایش و بازبینی انسانی' },
  { id: 'research', title: 'پژوهش', hint: 'جستجو، پرسش و آمار' },
  { id: 'lab', title: 'آزمایشگاه', hint: 'ارزیابی، مقایسهٔ مدل‌ها و ساختار داده' },
  { id: 'system', title: 'سامانه', hint: 'یکپارچه‌سازی و تنظیمات' },
]

export const TONES: Record<Tone, { card: string; icon: string; text: string; dot: string; glow: string; hex: string }> = {
  indigo: { card: 'from-indigo-500/[.16] to-indigo-500/[.03] border-indigo-300/[.14]', icon: 'bg-indigo-400/10 border-indigo-300/15 text-indigo-200', text: 'text-indigo-200/80', dot: 'bg-indigo-300', glow: 'rgba(99,102,241,.35)', hex: '#818cf8' },
  cyan: { card: 'from-cyan-400/[.13] to-cyan-400/[.03] border-cyan-300/[.14]', icon: 'bg-cyan-400/10 border-cyan-300/15 text-cyan-200', text: 'text-cyan-200/80', dot: 'bg-cyan-300', glow: 'rgba(34,211,238,.30)', hex: '#67e8f9' },
  amber: { card: 'from-amber-400/[.12] to-amber-400/[.03] border-amber-300/[.14]', icon: 'bg-amber-400/10 border-amber-300/15 text-amber-200', text: 'text-amber-200/80', dot: 'bg-amber-300', glow: 'rgba(251,191,36,.28)', hex: '#fcd34d' },
  violet: { card: 'from-violet-400/[.13] to-violet-400/[.03] border-violet-300/[.14]', icon: 'bg-violet-400/10 border-violet-300/15 text-violet-200', text: 'text-violet-200/80', dot: 'bg-violet-300', glow: 'rgba(167,139,250,.30)', hex: '#c4b5fd' },
  emerald: { card: 'from-emerald-400/[.12] to-emerald-400/[.03] border-emerald-300/[.14]', icon: 'bg-emerald-400/10 border-emerald-300/15 text-emerald-200', text: 'text-emerald-200/80', dot: 'bg-emerald-300', glow: 'rgba(52,211,153,.28)', hex: '#6ee7b7' },
  slate: { card: 'from-white/[.09] to-white/[.02] border-white/10', icon: 'bg-white/[.06] border-white/10 text-white/75', text: 'text-white/55', dot: 'bg-white/60', glow: 'rgba(255,255,255,.16)', hex: '#e2e8f0' },
  rose: { card: 'from-rose-400/[.12] to-rose-400/[.03] border-rose-300/[.14]', icon: 'bg-rose-400/10 border-rose-300/15 text-rose-200', text: 'text-rose-200/80', dot: 'bg-rose-300', glow: 'rgba(251,113,133,.28)', hex: '#fda4af' },
  sky: { card: 'from-sky-400/[.12] to-sky-400/[.03] border-sky-300/[.14]', icon: 'bg-sky-400/10 border-sky-300/15 text-sky-200', text: 'text-sky-200/80', dot: 'bg-sky-300', glow: 'rgba(56,189,248,.28)', hex: '#7dd3fc' },
}

const one = (label: string) => [{ id: 'main', label }]

export const SECTIONS: SectionDef[] = [
  { id: 'dashboard', num: '۰۲', title: 'داشبورد', group: 'archive', description: 'وضعیت آرشیو در یک نگاه', icon: LayoutDashboard, tone: 'indigo', tabs: one('نمای کلی'),
    metric: (s) => ({ label: `${fa(s.archive.cases)} پرونده · ${fa(s.counts.documents)} سند` }) },
  { id: 'cases', num: '۰۳', title: 'پرونده‌ها', group: 'archive', description: 'پرونده‌های بیمه‌ای و جزئیات هر پرونده', icon: FolderKanban, tone: 'cyan',
    tabs: [{ id: 'all', label: 'همه' }, { id: 'open', label: 'جاری' }, { id: 'closed', label: 'مختومه' }, { id: 'incomplete', label: 'ناقص' }],
    metric: (s) => ({ label: `${fa(s.cases.length)} پرونده`, attention: s.review_queue.length > 0 }) },
  { id: 'events', num: '۰۴', title: 'رویدادها', group: 'archive', description: 'همهٔ رویدادها روی یک خط زمان', icon: CalendarClock, tone: 'sky', tabs: one('خط زمان'),
    metric: (s) => ({ label: `${fa(s.events.length)} رویداد` }) },
  { id: 'documents', num: '۰۷', title: 'تیکت‌ها (اسناد)', group: 'archive', description: 'اسناد خام، متن کامل و قطعه‌ها', icon: FileText, tone: 'slate', tabs: one('اسناد'),
    metric: (s) => ({ label: `${fa(s.counts.documents)} سند · ${fa(s.counts.chunks)} قطعه` }) },
  { id: 'laws', num: '۱۵', title: 'قوانین و مستندات', group: 'archive', description: 'مواد قانونی، آیین‌نامه‌ها و پرونده‌های استنادکننده', icon: Scale, tone: 'amber', tabs: [{ id: 'browse', label: 'مرور' }, { id: 'search', label: 'جستجو' }, { id: 'add', label: 'افزودن ماده' }],
    metric: (s) => ({ label: `${fa(s.archive.laws)} ماده · ${fa(s.archive.citations)} استناد` }) },
  { id: 'entities', num: '۱۶', title: 'اشخاص و سازمان‌ها', group: 'archive', description: 'پروفایل هر شخص، شرکت و مرجع', icon: Users, tone: 'violet', tabs: [{ id: 'person', label: 'اشخاص' }, { id: 'org', label: 'سازمان‌ها' }],
    metric: (s) => ({ label: `${fa(s.archive.persons)} شخص · ${fa(s.archive.orgs)} سازمان` }) },
  { id: 'graphmap', num: '۲۰', title: 'نقشهٔ دانش', group: 'archive', description: 'آرشیو به‌صورت گراف یادداشت‌ها', icon: Network, tone: 'emerald', tabs: one('نقشه') },

  { id: 'ingest', num: '۰۵', title: 'بایگانی سند جدید', group: 'intake', description: 'استخراج ساختاریافته یا بارگذاری فایل', icon: FilePlus2, tone: 'emerald', tabs: [{ id: 'structured', label: 'استخراج ساختاریافته' }, { id: 'files', label: 'بارگذاری فایل' }, { id: 'runs', label: 'اجراهای خط لوله' }] },
  { id: 'editor', num: '۱۷', title: 'ویرایش مدخل‌ها', group: 'intake', description: 'ویرایش کامل هر مدخل و همگام‌سازی پرونده', icon: PenLine, tone: 'indigo', tabs: one('مدخل‌ها'),
    metric: (s) => ({ label: `${fa(s.counts.entries)} مدخل` }) },
  { id: 'review', num: '۰۹', title: 'بازبینی انسانی', group: 'intake', description: 'پرونده‌هایی که استخراج کامل نشد', icon: ClipboardCheck, tone: 'rose', tabs: one('صف بازبینی'),
    metric: (s) => ({ label: s.review_queue.length ? `${fa(s.review_queue.length)} در صف` : 'صف خالی', attention: s.review_queue.length > 0 }) },
  { id: 'taxonomy', num: '۰۸', title: 'طبقه‌بندی و برچسب‌ها', group: 'intake', description: 'درخت طبقه‌بندی و پوشش برچسب‌ها', icon: Tags, tone: 'cyan', tabs: one('برچسب‌ها'),
    metric: (s) => ({ label: `${fa(s.tags.length)} برچسب` }) },
  { id: 'labeling', num: '۱۰', title: 'برچسب‌گذاری و بازخورد', group: 'intake', description: 'داوری مرتبط بودن نتایج برای ارزیابی', icon: ThumbsUp, tone: 'amber', tabs: [{ id: 'judge', label: 'داوری نتایج' }, { id: 'labels', label: 'برچسب‌های ثبت‌شده' }] },

  { id: 'search', num: '۰۶', title: 'جستجو و پرسش', group: 'research', description: 'پاسخ مستند، جستجوی متن و آزمایشگاه بازیابی', icon: Search, tone: 'sky', tabs: [{ id: 'ask', label: 'پرسش با پاسخ مستند' }, { id: 'search', label: 'جستجوی متن' }, { id: 'lab', label: 'آزمایشگاه بازیابی' }] },
  { id: 'analytics', num: '۱۱', title: 'آمار آرشیو', group: 'research', description: 'تجمیع پرونده‌ها و پرسش زبانی از آمار', icon: ChartColumnBig, tone: 'violet', tabs: [{ id: 'overview', label: 'نمای کلی' }, { id: 'people', label: 'اشخاص و وکلا' }, { id: 'ask', label: 'پرسش از آمار' }] },

  { id: 'eval', num: '۱۳', title: 'ارزیابی بازیابی', group: 'lab', description: 'سنجش بازیاب با مجموعهٔ ارزیابی', icon: Gauge, tone: 'emerald', tabs: one('ارزیابی') },
  { id: 'bench', num: '۱۴', title: 'مقایسهٔ مدل‌ها', group: 'lab', description: 'یک پرسش، چند مدل، کنار هم', icon: FlaskConical, tone: 'rose', tabs: one('مقایسه') },
  { id: 'schema', num: '۱۲', title: 'ساختار داده و خط لوله', group: 'lab', description: 'آنچه سامانه ذخیره می‌کند و چگونه', icon: BookOpenText, tone: 'slate', tabs: [{ id: 'model', label: 'مدل داده' }, { id: 'pipeline', label: 'خط لوله' }, { id: 'form', label: 'فرم مدخل' }] },
  { id: 'gallery', num: '۱۸', title: 'نمایشگاه طراحی', group: 'lab', description: 'واژگان طراحی و مراحل نمایش', icon: Palette, tone: 'violet', tabs: [{ id: 'stages', label: 'مراحل نمایش' }, { id: 'tokens', label: 'نشانه‌های طراحی' }, { id: 'components', label: 'اجزا' }] },

  { id: 'webhooks', num: '۱۹', title: 'وب‌هوک‌ها و CI', group: 'system', description: 'اشتراک‌ها، تحویل‌ها و خط لولهٔ CI', icon: Webhook, tone: 'sky', tabs: [{ id: 'hooks', label: 'اشتراک‌ها' }, { id: 'deliveries', label: 'تحویل‌ها' }, { id: 'ci', label: 'CI' }] },
  { id: 'settings', num: '⚙', title: 'تنظیمات', group: 'system', description: 'مدل، بازیابی، گفتار و اتصال', icon: Settings2, tone: 'slate', tabs: [{ id: 'model', label: 'مدل' }, { id: 'retrieval', label: 'بازیابی' }, { id: 'speech', label: 'گفتار' }, { id: 'connection', label: 'اتصال' }] },
]

export const sectionById = (id: SectionId) => SECTIONS.find((s) => s.id === id)!
export const tabLabel = (id: SectionId, tab?: string) => sectionById(id).tabs.find((t) => t.id === tab)?.label

/** The archive icon used for the product mark. */
export const ArchiveIcon = Archive
