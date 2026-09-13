import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, LayoutGroup, motion, MotionConfig } from 'framer-motion'
import { useEffect } from 'react'
import { useHealth } from '@/api/queries'
import { useBackend } from '@/state/backend'
import { applyHash, isApplyingHash, serialize, useShell } from '@/state/shell'
import { AgentInbox } from '@/components/shell/AgentInbox'
import { CommandPalette } from '@/components/shell/CommandPalette'
import { HomeShell } from '@/components/shell/HomeShell'
import { PanelShell } from '@/components/shell/PanelShell'
import { Toasts } from '@/components/shell/Toasts'
import { WorkspaceShell } from '@/components/shell/WorkspaceShell'

/**
 * بیمه ایران حقوقی — two layers, one continuous surface:
 *   ۰۱ دستیار (AI home)  ⇄  پیشخوان بخش‌ها (sections)  →  section workspaces
 * Layers overlap during transitions so a section tile can morph into its
 * workspace (shared layoutId) instead of navigating away.
 */
export default function App() {
  const layer = useShell((s) => s.layer)
  const origin = useShell((s) => s.origin)
  useHealthSync()
  useDeepLinks()

  return (
    <MotionConfig reducedMotion="user">
      <LayoutGroup>
        <div className="relative h-full overflow-hidden">
          <AnimatePresence initial={false}>
            {layer === 'home' && (
              <motion.div key="home" className="absolute inset-0 overflow-y-auto"
                initial={{ opacity: 0, scale: 0.985 }} animate={{ opacity: 1, scale: 1 }}
                exit={origin === 'intent' ? { opacity: 0, scale: 1.035, filter: 'blur(6px)' } : { opacity: 0, scale: 0.99 }}
                transition={{ duration: 0.38, ease: [0.2, 0.7, 0.2, 1] }}>
                <HomeShell />
              </motion.div>
            )}
            {layer === 'panel' && (
              <motion.div key="panel" className="absolute inset-0 overflow-y-auto"
                initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, transition: { duration: 0.22 } }}
                transition={{ duration: 0.34, ease: [0.2, 0.7, 0.2, 1] }}>
                <PanelShell />
              </motion.div>
            )}
            {layer === 'workspace' && <WorkspaceShell key="workspace" />}
          </AnimatePresence>
        </div>
        <CommandPalette />
        <AgentInbox />
        <Toasts />
      </LayoutGroup>
    </MotionConfig>
  )
}

function useHealthSync() {
  const q = useHealth()
  const set = useBackend((s) => s.set)
  const qc = useQueryClient()
  useEffect(() => {
    if (q.data) set({ health: q.data, error: null })
    else if (q.error) set({ health: null, error: (q.error as Error).message })
  }, [q.data, q.error, set])
  // When the server comes back, refetch whatever failed while it was away.
  useEffect(() => { if (q.data) void qc.refetchQueries({ type: 'active', predicate: (x) => x.state.status === 'error' }) }, [q.data, qc])
}

/** #/home · #/panel · #/s/<section>/<tab>/<record>?q= — shareable, back-button friendly. */
function useDeepLinks() {
  useEffect(() => {
    if (location.hash && location.hash !== '#/') applyHash(location.hash)
    else history.replaceState(null, '', serialize(useShell.getState()))
    const onHash = () => { if (location.hash !== serialize(useShell.getState())) applyHash(location.hash) }
    window.addEventListener('hashchange', onHash)
    const off = useShell.subscribe((s) => { if (isApplyingHash()) return; const h = serialize(s); if (h !== location.hash) history.pushState(null, '', h) })
    return () => { window.removeEventListener('hashchange', onHash); off() }
  }, [])
}
