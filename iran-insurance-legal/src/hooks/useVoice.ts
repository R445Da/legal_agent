import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/api/endpoints'
import { useBackend } from '@/state/backend'
import { useSettings } from '@/state/settings'

/**
 * Voice composer state machine:  IDLE → LISTENING → PROCESSING → RESPONDING → COMPLETE
 *
 * When the server has speech-to-text (Groq Whisper / Gemini / faster-whisper,
 * app/rag/transcribe.py) the recording goes there — it is far better at
 * Persian than browsers are. Otherwise the browser's SpeechRecognition (fa-IR)
 * is used. The microphone level drives the orb and the waveform. Recording
 * *is* sending: when speech ends the transcript is submitted.
 */

export type VoicePhase = 'idle' | 'listening' | 'processing' | 'responding' | 'complete' | 'error'

type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  start: () => void; stop: () => void; abort: () => void
}

const Recognizer = (): (new () => Recognition) | undefined =>
  typeof window === 'undefined' ? undefined : ((window as unknown as Record<string, unknown>).SpeechRecognition ?? (window as unknown as Record<string, unknown>).webkitSpeechRecognition) as (new () => Recognition) | undefined

export function useVoice({ onFinal, reply }: { onFinal: (text: string) => Promise<void> | void; reply?: () => string | undefined }) {
  const [phase, setPhase] = useState<VoicePhase>('idle')
  const [level, setLevel] = useState(0)
  const [bars, setBars] = useState<number[]>(() => Array(24).fill(0))
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState<string | null>(null)

  const rec = useRef<Recognition | null>(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const audio = useRef<AudioContext | null>(null)
  const raf = useRef<number>(0)
  const text = useRef('')
  const done = useRef(false)

  const cleanup = useCallback(() => {
    cancelAnimationFrame(raf.current)
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    audio.current?.close().catch(() => {})
    audio.current = null
    setLevel(0)
    setBars(Array(24).fill(0))
  }, [])

  useEffect(() => () => { rec.current?.abort(); cleanup() }, [cleanup])

  const finish = useCallback(async (spoken: string) => {
    if (done.current) return
    done.current = true
    cleanup()
    const said = spoken.trim()
    if (!said) {
      setPhase('error'); setError('چیزی شنیده نشد — دوباره امتحان کنید.')
      setTimeout(() => setPhase((p) => (p === 'error' ? 'idle' : p)), 2200)
      return
    }
    setPhase('processing')
    await onFinal(said)
    const answer = reply?.()
    if (answer && 'speechSynthesis' in window) {
      setPhase('responding')
      await new Promise<void>((resolve) => {
        const u = new SpeechSynthesisUtterance(answer.slice(0, 280))
        u.rate = 1.04; u.onend = () => resolve(); u.onerror = () => resolve()
        window.speechSynthesis.speak(u)
        setTimeout(resolve, 12_000)
      })
    }
    setPhase('complete')
    setTimeout(() => setPhase((p) => (p === 'complete' ? 'idle' : p)), 1400)
  }, [cleanup, onFinal, reply])

  const meter = useCallback((s: MediaStream, onSilence?: () => void) => {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ctx = new Ctx()
    audio.current = ctx
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 256
    ctx.createMediaStreamSource(s).connect(analyser)
    const data = new Uint8Array(analyser.frequencyBinCount)
    let last = 0
    let heard = false
    let quietSince = performance.now()
    const tick = (now: number) => {
      analyser.getByteFrequencyData(data)
      if (now - last > 33) {
        last = now
        const slice = data.slice(2, 50)
        const avg = slice.reduce((a, b) => a + b, 0) / slice.length / 255
        const lv = Math.min(1, avg * 2.4)
        setLevel(lv)
        setBars(Array.from({ length: 24 }, (_, i) => Math.min(1, (data[3 + i * 2] / 255) * 1.6)))
        if (lv > 0.12) { heard = true; quietSince = now } else if (heard && onSilence && now - quietSince > 1600) { onSilence(); return }
      }
      raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
  }, [])

  const start = useCallback(async () => {
    if (phase === 'listening') return
    setError(null); setTranscript(''); text.current = ''; done.current = false
    const stt = useBackend.getState().health?.stt_available
    const R = stt ? undefined : Recognizer()
    if (!R && !stt) {
      setPhase('error')
      setError('گفتار به متن در دسترس نیست — STT را روی سرور فعال کنید یا از مرورگر Chrome/Edge استفاده کنید.')
      setTimeout(() => setPhase((p) => (p === 'error' ? 'idle' : p)), 3200)
      return
    }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      setPhase('error'); setError('اجازهٔ دسترسی به میکروفون داده نشد.')
      setTimeout(() => setPhase((p) => (p === 'error' ? 'idle' : p)), 2600)
      return
    }
    setPhase('listening')

    if (R) {
      meter(stream.current)
      const r = new R()
      r.lang = 'fa-IR'
      r.interimResults = true
      r.continuous = false
      r.onresult = (e) => {
        let s = ''
        for (let i = 0; i < e.results.length; i++) s += e.results[i][0].transcript
        text.current = s
        setTranscript(s)
      }
      r.onerror = (e) => { if (e.error !== 'aborted' && e.error !== 'no-speech') setError(`تشخیص گفتار: ${e.error}`) }
      r.onend = () => { void finish(text.current) }
      rec.current = r
      r.start()
      return
    }

    // Server-side speech-to-text with the backend chosen in settings.
    const chunks: Blob[] = []
    const mr = new MediaRecorder(stream.current)
    recorder.current = mr
    mr.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    mr.onstop = async () => {
      cleanup()
      setPhase('processing')
      try {
        const said = (await api.transcribe(new Blob(chunks, { type: mr.mimeType }), useSettings.getState().sttChoice)).text ?? ''
        setTranscript(said)
        await finish(said)
      } catch (err) {
        setPhase('error'); setError(`رونویسی ناموفق بود: ${(err as Error).message}`)
        setTimeout(() => setPhase((p) => (p === 'error' ? 'idle' : p)), 3000)
      }
    }
    mr.start()
    meter(stream.current, () => mr.state === 'recording' && mr.stop())
    setTimeout(() => mr.state === 'recording' && mr.stop(), 15_000)
  }, [phase, meter, finish, cleanup])

  const stop = useCallback(() => {
    if (rec.current) { rec.current.stop(); rec.current = null; return }
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])

  const cancel = useCallback(() => {
    done.current = true
    rec.current?.abort(); rec.current = null
    if (recorder.current?.state === 'recording') { recorder.current.onstop = null; recorder.current.stop() }
    cleanup(); setPhase('idle'); setTranscript('')
  }, [cleanup])

  return { phase, level, bars, transcript, error, start, stop, cancel }
}
