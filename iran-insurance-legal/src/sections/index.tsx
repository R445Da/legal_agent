import type { ComponentType } from 'react'
import type { SectionId } from '@/api/types'
import type { WorkspaceTab } from '@/state/shell'
import { AnalyticsView } from './analytics'
import { BenchView } from './bench'
import { CasesView } from './cases'
import { DashboardView } from './dashboard'
import { DocumentsView } from './documents'
import { EditorView } from './editor'
import { EntitiesView } from './entities'
import { EvalView } from './eval'
import { EventsView } from './events'
import { GalleryView } from './gallery'
import { GraphMapView } from './graphmap'
import { IngestView } from './ingest'
import { LabelingView } from './labeling'
import { LawsView } from './laws'
import { ReviewView } from './review'
import { SchemaView } from './schema'
import { SearchView } from './search'
import { SettingsView } from './settings'
import { TaxonomyView } from './taxonomy'
import { WebhooksView } from './webhooks'

/** Section id → workspace. ۰۱ «دستیار پرونده» is the home layer, not a section. */
export const SECTION_VIEWS: Record<SectionId, ComponentType<{ ws: WorkspaceTab }>> = {
  dashboard: DashboardView, cases: CasesView, events: EventsView, ingest: IngestView, search: SearchView,
  documents: DocumentsView, taxonomy: TaxonomyView, review: ReviewView, labeling: LabelingView, analytics: AnalyticsView,
  schema: SchemaView, eval: EvalView, bench: BenchView, laws: LawsView, entities: EntitiesView, editor: EditorView,
  gallery: GalleryView, webhooks: WebhooksView, graphmap: GraphMapView, settings: SettingsView,
}
