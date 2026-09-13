import { useEffect, useMemo } from 'react'
import { create } from 'zustand'
import type { SectionId } from '@/api/types'
import { tabLabel } from '@/sections/registry'
import { activeTab, isRunTab, useShell } from './shell'

/**
 * The safe application context the assistant inherits: the section, its view,
 * the open record (a case, document, law, entity or entry run) and filters.
 * Sections publish the human-readable parts with `usePublishContext`.
 */
export interface WorkspaceContext {
  section?: SectionId
  tab?: string
  tabLabel?: string
  entityId?: string
  entityKind?: 'case' | 'document' | 'law' | 'person' | 'org' | 'entry' | 'run'
  entityLabel?: string
  /** For a case: the ids of its documents, so a question is answered from this case only. */
  documentIds?: string[]
  view?: string
  filters?: Record<string, string>
}

type Extras = Pick<WorkspaceContext, 'entityLabel' | 'entityKind' | 'documentIds' | 'view' | 'filters'>

interface ContextState {
  extras: Partial<Record<SectionId, Extras>>
  publish: (section: SectionId, extras: Extras) => void
}

export const useContextStore = create<ContextState>((set) => ({
  extras: {},
  publish: (section, extras) => set((s) => ({ extras: { ...s.extras, [section]: extras } })),
}))

export function usePublishContext(section: SectionId, extras: Extras) {
  const publish = useContextStore((s) => s.publish)
  const key = JSON.stringify(extras)
  useEffect(() => {
    publish(section, extras)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, key, publish])
}

export function currentContext(): WorkspaceContext {
  const shell = useShell.getState()
  if (shell.layer !== 'workspace' || !shell.active) return {}
  const t = activeTab(shell)
  if (!t) return {}
  const extras = useContextStore.getState().extras[t.section] ?? {}
  const record = t.active ?? undefined
  return {
    section: t.section,
    tab: t.tab,
    tabLabel: tabLabel(t.section, t.tab),
    entityId: record,
    entityKind: record ? (isRunTab(record) ? 'run' : extras.entityKind) : undefined,
    entityLabel: record ? extras.entityLabel : undefined,
    documentIds: record ? extras.documentIds : undefined,
    view: record ? extras.view : undefined,
    filters: extras.filters,
  }
}

export function useCurrentContext(): WorkspaceContext {
  const layer = useShell((s) => s.layer)
  const active = useShell((s) => s.active)
  const tabs = useShell((s) => s.tabs)
  const extras = useContextStore((s) => s.extras)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => currentContext(), [layer, active, tabs, extras])
}
