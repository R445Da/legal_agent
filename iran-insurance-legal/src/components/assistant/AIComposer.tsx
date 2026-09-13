import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUp, Mic, Square, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { ask } from '@/assistant/runtime'
import { useVoice } from '@/hooks/useVoice'
import { cn } from '@/lib/utils'
import { useAssistant } from '@/state/assistant'
import { useVoiceSignal } from '@/state/voice'
import { Waveform } from './Waveform'

/**
 * The composer: text and voice in one control (no separate voice mode).
 * Recording *is* sending — when speech ends, the transcript is submitted.
 */
export function AIComposer({ origin, size = 'lg', placeholder = 'بپرسید، ثبت کنید یا بگویید چه کاری انجام شود…', autoFocus, seed, className }: {
  origin: 'home' | 'assistant'
  size?: 'lg' | 'sm'
  placeholder?: string
  autoFocus?: boolean
  seed?: { text: string; n: number }
  className?: string
}) {
  const [value, setValue] = useState('')
  const busy = useAssistant((s) => s.busy)
  const input = useRef<HTMLTextAreaElement>(null)
  const setSignal = useVoiceSignal((s) => s.set)

  const lastReply = useCallback(() => [...useAssistant.getState().messages].reverse().find((m) => m.role === 'assistant')?.text, [])
  const voice = useVoice({ onFinal: (t) => ask(t, 'voice'), reply: lastReply })

  useEffect(() => { setSignal(voice.phase, voice.level) }, [voice.phase, voice.level, setSignal])
  useEffect(() => { if (seed) { setValue(seed.text); input.current?.focus() } }, [seed])
  useEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.min(el.scrollHeight, size === 'lg' ? 140 : 110)}px`
  }, [value, size])

  const submit = () => {
    const text = value.trim()
    if (!text || busy) return
    setValue('')
    void ask(text, origin)
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() }
    if (e.key === 'Escape' && voice.phase === 'listening') voice.cancel()
  }

  const listening = voice.phase === 'listening'
  const lg = size === 'lg'

  return (
    <div className={cn('relative w-full', className)}>
      <form onSubmit={(e) => { e.preventDefault(); submit() }}
        className={cn('glass relative flex items-end gap-2 transition-[border-color,box-shadow] duration-300', lg ? 'rounded-[28px] p-2 ps-3' : 'rounded-2xl p-1.5 ps-2',
          listening && 'border-cyan-300/30 shadow-[0_0_0_4px_rgba(34,211,238,.06),0_24px_80px_rgba(0,0,0,.3)]',
          busy && !listening && 'border-indigo-300/20')}>
        <div className="relative min-w-0 flex-1 self-center">
          <AnimatePresence mode="wait" initial={false}>
            {listening || voice.phase === 'processing' || voice.phase === 'responding' ? (
              <motion.div key="voice" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                className={cn('flex items-center gap-3', lg ? 'min-h-12 px-2' : 'min-h-9 px-1')}>
                {listening ? <Waveform bars={voice.bars} className={lg ? 'h-7' : 'h-5'} /> : <Waveform active className={lg ? 'h-7' : 'h-5'} color={voice.phase === 'responding' ? 'bg-teal-200/70' : 'bg-indigo-200/70'} />}
                <span className={cn('min-w-0 flex-1 truncate', lg ? 'text-sm' : 'text-xs', voice.transcript ? 'text-white/85' : 'text-white/40')}>
                  {voice.phase === 'processing' ? <span className="shimmer-text">{voice.transcript || 'در حال رونویسی…'}</span>
                    : voice.phase === 'responding' ? <span className="text-teal-100/80">در حال خواندن پاسخ…</span>
                    : voice.transcript || 'در حال شنیدن — بگویید چه کاری انجام شود'}
                </span>
              </motion.div>
            ) : (
              <motion.textarea key="text" ref={input} rows={1} value={value} autoFocus={autoFocus}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                onChange={(e) => setValue(e.target.value)} onKeyDown={onKey}
                placeholder={busy ? 'دستیار در حال کار است…' : placeholder}
                aria-label="پیام به دستیار"
                className={cn('block w-full resize-none bg-transparent outline-none placeholder:text-white/25', lg ? 'px-2 py-3 text-[15px] leading-6' : 'px-1 py-2 text-[13px] leading-5')} />
            )}
          </AnimatePresence>
        </div>

        {listening && (
          <button type="button" onClick={voice.cancel} aria-label="لغو ضبط" className={cn('flex shrink-0 items-center justify-center rounded-2xl text-white/45 hover:text-white', lg ? 'h-11 w-9' : 'h-8 w-7')}>
            <X className="h-4 w-4" />
          </button>
        )}
        <VoiceButton phase={voice.phase} level={voice.level} size={size} onStart={voice.start} onStop={voice.stop} />
        <button type="submit" disabled={!value.trim() || busy || listening} aria-label="ارسال"
          className={cn('flex shrink-0 items-center justify-center bg-white text-ink-900 transition hover:bg-white/90 active:scale-95 disabled:bg-white/10 disabled:text-white/30', lg ? 'h-11 w-11 rounded-2xl' : 'h-8 w-8 rounded-xl')}>
          <ArrowUp className={cn(lg ? 'h-[18px] w-[18px]' : 'h-4 w-4', '-rotate-90')} strokeWidth={2.2} />
        </button>
      </form>
      <AnimatePresence>
        {voice.error && voice.phase === 'error' && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="absolute inset-x-3 top-full mt-2 text-center text-xs text-rose-200/80">{voice.error}</motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function VoiceButton({ phase, level, size, onStart, onStop }: { phase: string; level: number; size: 'lg' | 'sm'; onStart: () => void; onStop: () => void }) {
  const listening = phase === 'listening'
  const lg = size === 'lg'
  return (
    <button type="button" onClick={listening ? onStop : onStart} aria-label={listening ? 'توقف و ارسال' : 'گفتن به دستیار'} aria-pressed={listening}
      disabled={phase === 'processing' || phase === 'responding'}
      className={cn('relative flex shrink-0 items-center justify-center border transition active:scale-95', lg ? 'h-11 w-11 rounded-2xl' : 'h-8 w-8 rounded-xl',
        listening ? 'border-cyan-300/30 bg-cyan-300/10 text-cyan-100' : 'border-white/10 bg-white/[.05] text-white/70 hover:bg-white/[.09] hover:text-white')}>
      {listening && <motion.span className="absolute inset-0 rounded-[inherit] border border-cyan-200/40" animate={{ scale: 1 + level * 0.5, opacity: 0.2 + level }} transition={{ duration: 0.08 }} />}
      {listening ? <Square className={lg ? 'h-3.5 w-3.5' : 'h-3 w-3'} fill="currentColor" /> : <Mic className={lg ? 'h-[18px] w-[18px]' : 'h-4 w-4'} />}
    </button>
  )
}
