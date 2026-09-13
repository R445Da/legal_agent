"""
The assistant reading its turn aloud.

Filing a case by voice is only half a conversation if the answers have to be
read off the screen. When the speaker toggle is on, each new assistant turn —
a question from the filing dialogue, an acknowledgement, an answer — is spoken,
so the whole flow works with the screen ignored.

This uses the browser's own `speechSynthesis` rather than a server-side voice.
The reasons are practical: it needs no model download, no ffmpeg round trip and
no audio bytes crossing the wire, it starts speaking immediately, and it is the
same mechanism the original prototype used (`app/static/app.html` preferred an
`fa-*` voice for exactly this). A server-side Persian voice would sound better
and is worth revisiting, but it would mean shipping a ~60 MB model and adding
latency to every turn.

Only the newest turn is spoken, and only once: the component is keyed on a
counter, so Streamlit's reruns — which re-execute the whole script on every
interaction — do not replay the same sentence each time.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

_KEY = "_spoken_seq"


def enabled() -> bool:
    return bool(st.session_state.get("speak_replies"))


def toggle() -> None:
    """The speaker switch, for the composer row."""
    st.toggle(
        "خواندن پاسخ‌ها با صدا", key="speak_replies",
        help="پاسخ دستیار با صدای مرورگر خوانده می‌شود — برای وقتی که با گفتار کار می‌کنید.",
    )


def say(text: str, *, seq: int) -> None:
    """Speak `text` once. `seq` must increase for each new utterance."""
    if not enabled():
        return
    speech = (text or "").strip()
    if not speech or st.session_state.get(_KEY) == seq:
        return
    st.session_state[_KEY] = seq

    # Trimmed: a spoken paragraph is tiring, and the screen still has the full
    # text. Citation markers read as noise out loud, so they go.
    speech = speech.replace("[", " ").replace("]", " ")
    if len(speech) > 600:
        speech = speech[:600] + "…"

    components.html(
        f"""<script>
        (function () {{
          const text = {json.dumps(speech)};
          const synth = window.parent.speechSynthesis || window.speechSynthesis;
          if (!synth) return;
          function speak() {{
            const voices = synth.getVoices() || [];
            const utter = new SpeechSynthesisUtterance(text);
            // A Persian voice if the machine has one, otherwise any Arabic
            // -script voice, otherwise the default — which at least reads the
            // digits and punctuation correctly.
            const persian = voices.find(v => /^fa/i.test(v.lang))
                         || voices.find(v => /^ar/i.test(v.lang));
            if (persian) utter.voice = persian;
            utter.lang = (persian && persian.lang) || 'fa-IR';
            utter.rate = 1.0;
            synth.cancel();
            synth.speak(utter);
          }}
          // getVoices() is empty until the list loads, on most browsers.
          if ((synth.getVoices() || []).length) speak();
          else synth.addEventListener('voiceschanged', speak, {{ once: true }});
        }})();
        </script>""",
        height=0,
    )
