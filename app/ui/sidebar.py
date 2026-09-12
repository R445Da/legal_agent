"""
The control panel: model selection, per-model tuning knobs, retrieval dials.

The knob section is *generated from the selected model*, not written by hand.
`registry.catalog()` attaches `knobs` (from `app.llm.knobs`) to every entry, and
this module renders one widget per entry. Pick a model that supports
`reasoning_effort` and the control appears; pick `groq/compound-mini` and it
disappears, because sending it would be a 400. The collected values are passed
straight through to `generate(**knobs)`.

Retrieval dials are separate: they are model-independent and are the ones that
actually govern latency in this system (the cross-encoder runs on CPU per
candidate, regardless of which LLM answers).
"""

import streamlit as st

from app.llm import registry
from app.rag import rerank
from app.ui import resources
from app.ui.theme import fa_ms, fa_num


def _fmt_ms(ms: float) -> str:
    return fa_ms(ms)


@st.cache_data(ttl=600, show_spinner="در حال شناسایی مدل‌ها…")
def _catalog(autostart: bool) -> list[dict]:
    """Cached so re-runs don't re-hit each gateway's /models.

    The TTL is long on purpose: a short one made the app pause mid-session while
    it re-queried every gateway, which reads as the page needing a refresh. The
    «بازخوانی · اجرای Ollama» button clears it on demand."""
    return registry.catalog(autostart_ollama=autostart)


def _model_section() -> dict:

    if st.button("بازخوانی · اجرای Ollama", use_container_width=True):
        _catalog.clear()
        registry.ensure_ollama(autostart=True)
        st.rerun()

    entries = _catalog(False)
    if not entries:
        st.error("مدلی یافت نشد. GROQ_API_KEY / OPENAI_BASE_URL را بررسی کنید یا Ollama را اجرا کنید.")
        st.stop()

    # Options are ids, not entry dicts: `st.cache_data` hands back a fresh copy
    # of the catalog on every re-run, so dict options would be new objects each
    # time and the widget could not match its stored selection back to one.
    by_id = {e["id"]: e for e in entries}
    ids = list(by_id)
    default = registry.default_id()
    available_ids = [i for i in ids if by_id[i]["available"]]

    # Land on a model that actually works. Streamlit's selectbox restores its
    # stored selection over any `index=`, so both the stored pick and the
    # configured default are checked: if whichever would be shown is
    # unavailable (a gateway 403s, Ollama is broken) but something else works,
    # switch to that and say so — otherwise every message fires at a dead
    # endpoint and only fails when you send it.
    shown = st.session_state.get("model_id")
    if shown not in by_id:
        shown = default if default in by_id else (ids[0] if ids else None)
    if shown in by_id and not by_id[shown]["available"] and available_ids:
        prefer = default if default in available_ids else available_ids[0]
        st.session_state["model_id"] = prefer
        st.warning(
            f"«{by_id[shown]['label']}» در دسترس نیست — به «{by_id[prefer]['label']}» "
            "تغییر داده شد."
        )
        shown = prefer

    index = ids.index(shown) if shown in ids else 0

    def _label(model_id: str) -> str:
        entry = by_id[model_id]
        return ("" if entry["available"] else "⚠ ") + entry["label"]

    entry = by_id[st.selectbox("مدل فعال", ids, index=index, format_func=_label, key="model_id")]

    if not entry["available"]:
        st.error(
            (entry["reason"] or "این مدل در دسترس نیست") + " — پیام‌ها ارسال نخواهند شد."
        )

    notes = registry.notes(entries)
    if notes:
        with st.expander(f"وضعیت اتصال ({fa_num(len(notes))})"):
            for note in notes:
                st.caption(f"• {note}")

    with st.expander("دریافت مدل Ollama"):
        tag = st.text_input("نام مدل", placeholder="qwen2.5:3b", key="pull_tag")
        if st.button("دریافت", disabled=not tag):
            try:
                with st.spinner(f"در حال دریافت {tag} — ممکن است چند دقیقه طول بکشد…"):
                    registry.pull_ollama_model(tag)
                _catalog.clear()
                st.success(f"{tag} دریافت شد")
                st.rerun()
            except Exception as error:  # noqa: BLE001 — surfaced to the user
                st.error(str(error))

    return entry


def _speech_section() -> None:
    """Which model turns speech into text. It belongs here beside the answer
    model — both are "which model does this job" choices, and neither is a
    per-message decision."""
    from app.rag import transcribe as stt

    if not stt.enabled():
        st.caption("گفتار به متن غیرفعال است (STT=0).")
        return
    options = stt.choices()
    labels = dict(options)
    ids = [c for c, _ in options]
    default = stt.default_choice()
    st.selectbox(
        "مدل گفتار به متن", ids,
        index=ids.index(default) if default in ids else 0,
        format_func=lambda c: labels[c], key="agent_stt",
        help="مدل‌های Groq روی شبکه اجرا می‌شوند و بسیار سریع‌ترند؛ مدل‌های محلی نیازی به کلید ندارند.",
    )


def _knob_section(entry: dict) -> dict:
    """One widget per knob the selected model advertises."""
    if entry["reasoning"]:
        st.caption("مدل استدلالی — توکن‌های «فکر کردن» هم از سقف خروجی کم می‌شوند.")

    values: dict = {}
    for knob in entry["knobs"]:
        key, label, help_text = knob["key"], knob["label"], knob["help"]
        widget_key = f"knob::{key}"
        if knob["kind"] == "select":
            values[key] = st.select_slider(
                label, options=knob["options"], value=knob["default"],
                key=widget_key, help=help_text,
            )
        elif knob["kind"] == "slider":
            values[key] = st.slider(
                label, min_value=knob["min"], max_value=knob["max"],
                value=knob["default"], step=knob["step"],
                key=widget_key, help=help_text,
            )
        else:
            values[key] = st.toggle(label, value=knob["default"], key=widget_key, help=help_text)

    # max_tokens is a generate() argument in its own right, not a **knob.
    values["max_tokens"] = int(values.get("max_tokens", 1024))
    return values


def _retrieval_section() -> tuple[int, dict]:
    st.caption("مستقل از مدل — زمان پردازندهٔ سامانه اینجا صرف می‌شود.")

    top_k = st.slider("تعداد قطعه‌های داده‌شده به مدل", 1, 12, 5, key="top_k")
    hybrid = st.toggle(
        "جستجوی ترکیبی (برداری + متنی، RRF)", value=True, key="hybrid",
        help="خاموش = فقط برداری. سمت متنی است که نام‌ها، شماره‌ها و ارجاع‌های قانونی را می‌گیرد.",
    )
    candidates = st.slider(
        "نامزدهای مرحلهٔ اول (هر سمت)", 5, 60, 30, step=5, key="candidates",
        help="عمق فراخوانی. ارزان است — یک پرسمان Postgres، نه یک مدل.",
    )

    rerank_on = st.toggle(
        "بازرتبه‌بندی متقاطع", value=rerank.enabled(), key="rerank",
        help="بزرگ‌ترین اهرم دقت و در عین حال بیشترین هزینهٔ زمانی: یک گذر پردازنده به ازای هر نامزد.",
    )
    rerank_top = 12
    rerank_model = rerank.default_model()
    if rerank_on:
        rerank_top = st.slider(
            "تعداد نامزدهای بازرتبه‌بندی‌شده", 3, 30, 12, key="rerank_top",
            help="زمان با این عدد خطی است. نصف کردنش تقریباً زمان بازرتبه‌بندی را نصف می‌کند.",
        )
        names = [m for m, _ in rerank.CHOICES]
        labels = dict(rerank.CHOICES)
        default_index = names.index(rerank_model) if rerank_model in names else 0
        rerank_model = st.selectbox(
            "مدل بازرتبه‌بندی", names, index=default_index,
            format_func=lambda m: labels.get(m, m), key="rerank_model",
            help="فقط مدل‌های چندزبانه فارسی را درست امتیاز می‌دهند؛ مدل‌های انگلیسی صرفاً کف سرعت برای سنجش‌اند.",
        )
        if st.button("پیش‌بارگذاری بازرتبه‌بند", use_container_width=True):
            resources.warm_reranker(rerank_model)
            st.success("بارگذاری شد")

    return top_k, {
        "hybrid": hybrid,
        "rerank": rerank_on,
        "candidates": candidates,
        "rerank_top": rerank_top,
        "rerank_model": rerank_model,
    }


def expanded() -> bool:
    return st.session_state.setdefault("show_panel", True)


def render() -> dict:
    """Draw the control panel; return everything the views need to run a query.

    Same collapse mechanic as the section rail on the right: a chevron of our
    own, not Streamlit's sidebar. Streamlit's own control vanishes from the DOM
    once collapsed, which left the panel unreachable — and there is no API to
    reopen it from Python.
    """
    entry = _model_section()
    _speech_section()
    with st.expander("کلیدهای تنظیم مدل"):
        knobs = _knob_section(entry)
    with st.expander("بازیابی"):
        top_k, retrieval = _retrieval_section()
        st.caption(f"مدل تعبیه · {resources.warm_embeddings().split('/')[-1]}")

    max_tokens = knobs.pop("max_tokens")
    return {
        "entry": entry,
        "model_id": entry["id"],
        "llm": registry.resolve(entry["id"]),
        "knobs": knobs,          # -> generate(**knobs)
        "max_tokens": max_tokens,
        "top_k": top_k,
        "retrieval": retrieval,  # -> retrieve_scored(**retrieval)
    }


def latency_bar(retrieval_trace: dict, generate_ms: float | None) -> None:
    """Where the wall clock went, so a knob change can be judged immediately."""
    vec = retrieval_trace.get("vector_ms", 0.0)
    lex = retrieval_trace.get("lexical_ms", 0.0)
    rer = retrieval_trace.get("rerank_ms", 0.0)
    gen = generate_ms or 0.0
    cols = st.columns(4)
    cols[0].metric("برداری", _fmt_ms(vec))
    cols[1].metric("متنی", _fmt_ms(lex))
    cols[2].metric("بازرتبه‌بندی", _fmt_ms(rer), help=f"{fa_num(retrieval_trace.get('pairs_scored', 0))} جفت امتیازدهی شد")
    cols[3].metric("تولید پاسخ", _fmt_ms(gen))
