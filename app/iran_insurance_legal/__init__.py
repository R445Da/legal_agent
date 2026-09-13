"""
بیمه ایران حقوقی — the server side of the React front end (`iran-insurance-legal/`).

Additive only: nothing in the Streamlit UI or the RAG engine depends on this
package. The React app talks to the existing JSON API in `app/main.py` for
almost everything (/assistant, /runs, /cases, /laws, /entities, /entries,
/documents, /labels, /eval, /bench, /models, /hooks, /ci/events, /graph/vault…)
and to the routes here for what Streamlit gets by importing the engine directly:

    GET   /legal/api/state                the archive bundle app/ui/data.py loads
    GET   /legal/api/options              vocabularies + retrieval / STT / pipeline choices
    POST  /legal/api/route                intent only — nothing is executed
    POST  /legal/api/ask                  grounded answer with the full retrieval panel
    POST  /legal/api/retrieve             retrieval only, with per-stage timings
    POST  /legal/api/runs/{id}/advance    resume an entry run past a human gate
    POST  /legal/api/runs/{id}/abandon    stop an entry run
    POST  /legal/api/transcribe           speech-to-text with a chosen backend
    GET   /legal/                         the built SPA (`cd iran-insurance-legal && npm run build`)
"""

from app.iran_insurance_legal.router import mount_spa, router

__all__ = ["router", "mount_spa"]
