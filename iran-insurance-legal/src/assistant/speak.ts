/** Short spoken replies (the Streamlit `speak.py` toggle), Persian voice when the browser has one. */
export function speak(text: string) {
  if (typeof window === 'undefined' || !('speechSynthesis' in window) || !text.trim()) return
  const u = new SpeechSynthesisUtterance(text.replace(/\[\d+\]/g, '').slice(0, 320))
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.startsWith('fa'))
  if (voice) u.voice = voice
  u.lang = voice?.lang ?? 'fa-IR'
  u.rate = 1.02
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(u)
}
