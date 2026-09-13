import { create } from 'zustand'
import type { OrbState } from '@/assistant/types'
import type { VoicePhase } from '@/hooks/useVoice'

/** Mirrors the active voice session so every orb on screen can react to it. */
interface VoiceSignal { phase: VoicePhase; level: number; set: (phase: VoicePhase, level: number) => void }
export const useVoiceSignal = create<VoiceSignal>((set) => ({ phase: 'idle', level: 0, set: (phase, level) => set({ phase, level }) }))

/** The orb shows voice first (it is the most immediate), then the agent's own state. */
export function blendOrb(agent: OrbState, voice: VoicePhase): OrbState {
  if (voice === 'listening') return 'listening'
  if (voice === 'processing' && agent === 'idle') return 'processing'
  if (voice === 'responding') return 'responding'
  if (voice === 'error') return 'error'
  return agent
}
