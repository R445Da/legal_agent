import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { SectionId } from '@/api/types'
import { SECTIONS, sectionById } from '@/sections/registry'

/**
 * Presentation state only: which layer is showing, which sections are open as
 * workspace tabs, and which records (a case, a document, a law, an entry run)
 * are open as tabs *inside* each section. No archive data lives here.
 *
 *   Home (۰۱ دستیار) ─┬─ Control panel ── section tabs ── record / run tabs
 *                     └─ (intent) ─────────┘
 */

export type Layer = 'home' | 'panel' | 'workspace'
export type Origin = 'card' | 'intent' | 'tab' | 'link'

/** Run tabs are stored as `run:<uuid>` so a deep link can tell them apart. */
export const RUN_PREFIX = 'run:'
export const isRunTab = (id: string | null | undefined) => !!id && id.startsWith(RUN_PREFIX)

export interface InnerTab { id: string; label: string }
export interface WorkspaceTab {
  section: SectionId
  tab: string
  inner: InnerTab[]
  active: string | null // inner tab id, or null = the section's main view
  query?: string
}

interface ShellState {
  layer: Layer
  tabs: WorkspaceTab[]
  active: SectionId | null
  origin: Origin
  paletteOpen: boolean
  assistantOpen: boolean
  inboxOpen: boolean

  goHome: () => void
  goPanel: () => void
  open: (section: SectionId, opts?: { tab?: string; record?: string; label?: string; query?: string; origin?: Origin }) => void
  close: (section: SectionId) => void
  setTab: (tab: string) => void
  setQuery: (query: string) => void
  openInner: (id: string, label?: string, section?: SectionId) => void
  closeInner: (id: string) => void
  focusInner: (id: string | null) => void
  openRun: (runId: string, label?: string, origin?: Origin) => void
  setPalette: (open: boolean) => void
  setAssistant: (open: boolean) => void
  setInbox: (open: boolean) => void
}

const defaultTab = (s: SectionId) => sectionById(s).tabs[0].id

export const useShell = create<ShellState>()(
  persist(
    (set, get) => ({
      layer: 'home',
      tabs: [],
      active: null,
      origin: 'card',
      paletteOpen: false,
      assistantOpen: false,
      inboxOpen: false,

      goHome: () => set({ layer: 'home', assistantOpen: false }),
      goPanel: () => set({ layer: 'panel', assistantOpen: false }),

      open: (section, opts = {}) => set((s) => {
        const existing = s.tabs.find((t) => t.section === section)
        const valid = (tab?: string) => (tab && sectionById(section).tabs.some((t) => t.id === tab) ? tab : undefined)
        const base: WorkspaceTab = existing ?? { section, tab: defaultTab(section), inner: [], active: null }
        let next: WorkspaceTab = { ...base, tab: valid(opts.tab) ?? base.tab, query: opts.query ?? base.query }
        if (opts.record) {
          const known = next.inner.find((i) => i.id === opts.record)
          const inner = known
            ? next.inner.map((i) => (i.id === opts.record && opts.label ? { ...i, label: opts.label } : i))
            : [...next.inner, { id: opts.record, label: opts.label ?? shortLabel(opts.record) }]
          next = { ...next, inner, active: opts.record }
        } else if (opts.tab) next = { ...next, active: null }
        const tabs = existing ? s.tabs.map((t) => (t.section === section ? next : t)) : [...s.tabs, next]
        return { tabs, active: section, layer: 'workspace', origin: opts.origin ?? 'tab' }
      }),

      close: (section) => set((s) => {
        const idx = s.tabs.findIndex((t) => t.section === section)
        const tabs = s.tabs.filter((t) => t.section !== section)
        if (s.active !== section) return { tabs }
        const neighbour = tabs[Math.min(idx, tabs.length - 1)]
        return neighbour ? { tabs, active: neighbour.section, origin: 'tab' } : { tabs, active: null, layer: 'panel' }
      }),

      setTab: (tab) => set((s) => ({ tabs: s.tabs.map((t) => (t.section === s.active ? { ...t, tab, active: null } : t)) })),
      setQuery: (query) => set((s) => ({ tabs: s.tabs.map((t) => (t.section === s.active ? { ...t, query } : t)) })),

      openInner: (id, label, section) => {
        const target = section ?? get().active
        if (!target) return
        get().open(target, { record: id, label, origin: 'tab' })
      },

      closeInner: (id) => set((s) => ({
        tabs: s.tabs.map((t) => {
          if (t.section !== s.active) return t
          const idx = t.inner.findIndex((i) => i.id === id)
          const inner = t.inner.filter((i) => i.id !== id)
          const active = t.active === id ? (inner[Math.min(idx, inner.length - 1)]?.id ?? null) : t.active
          return { ...t, inner, active }
        }),
      })),

      focusInner: (id) => set((s) => ({ tabs: s.tabs.map((t) => (t.section === s.active ? { ...t, active: id } : t)) })),

      openRun: (runId, label = 'ثبت مطلب', origin = 'intent') => get().open('ingest', { tab: 'runs', record: `${RUN_PREFIX}${runId}`, label, origin }),

      setPalette: (paletteOpen) => set({ paletteOpen }),
      setAssistant: (assistantOpen) => set({ assistantOpen, inboxOpen: assistantOpen ? false : get().inboxOpen }),
      setInbox: (inboxOpen) => set({ inboxOpen, assistantOpen: inboxOpen ? false : get().assistantOpen }),
    }),
    { name: 'legal.shell', partialize: (s) => ({ tabs: s.tabs }) },
  ),
)

function shortLabel(id: string) {
  if (isRunTab(id)) return 'ثبت مطلب'
  return /^[0-9a-f]{8}-/.test(id) ? id.slice(0, 8) : id
}

export const activeTab = (s: Pick<ShellState, 'tabs' | 'active'>) => s.tabs.find((t) => t.section === s.active)

// ------------------------------------------------------------------ deep links
// #/home · #/panel · #/s/<section>/<tab>[/<record>][?q=<query>]

export function serialize(s: Pick<ShellState, 'layer' | 'tabs' | 'active'>): string {
  if (s.layer === 'home') return '#/home'
  if (s.layer === 'panel' || !s.active) return '#/panel'
  const t = activeTab(s)
  if (!t) return '#/panel'
  const rec = t.active ? `/${encodeURIComponent(t.active)}` : ''
  const q = t.query && ['search', 'documents', 'laws', 'entities'].includes(t.section) ? `?q=${encodeURIComponent(t.query)}` : ''
  return `#/s/${t.section}/${t.tab}${rec}${q}`
}

let applying = false
/** True while a URL is being applied — history sync must not echo it back. */
export const isApplyingHash = () => applying

export function applyHash(hash: string) {
  applying = true
  try {
    apply(hash)
  } finally {
    applying = false
  }
  const normalized = serialize(useShell.getState())
  if (normalized !== location.hash) history.replaceState(null, '', normalized)
}

function apply(hash: string) {
  useShell.setState({ paletteOpen: false, inboxOpen: false })
  const s = useShell.getState()
  const [path, search] = hash.replace(/^#/, '').split('?')
  const parts = path.split('/').filter(Boolean)
  if (parts[0] === 'panel') return s.goPanel()
  if (parts[0] === 's' && SECTIONS.some((m) => m.id === parts[1])) {
    const query = new URLSearchParams(search ?? '').get('q') ?? undefined
    const record = parts[3] ? decodeURIComponent(parts[3]) : undefined
    s.open(parts[1] as SectionId, { tab: parts[2], record, query, origin: 'link' })
    if (!record) useShell.getState().focusInner(null)
    return
  }
  s.goHome()
}
