"""۱۸ نمایشگاه طراحی — the design vocabulary and the demo stages, on sample data."""

import inspect

import streamlit as st

from app.demo.stages import STAGES
from app.rag.orchestrator import _INTENT_FA
from app.ui import components, samples
from app.ui import theme as th
from app.ui.theme import (
    answer, card, case_id, chips, esc, fa_num, kv, ledger, panel, stamp, timeline,
)


def _demo(title: str, code: str, render) -> None:
    """One gallery entry: the rendered helper on the right, its call on the left."""
    left, right = st.columns([2, 3])
    with left:
        st.markdown(f"**{title}**")
        st.code(code.strip(), language="python")
    with right:
        render()
    st.divider()


def _tokens() -> None:
    for name, palette_ in (("روشن", th.LIGHT), ("تیره", th.DARK)):
        st.markdown(f"**پالت {name}**")
        boxes = "".join(
            f"<div style='display:inline-block;width:118px;margin:4px;text-align:center'>"
            f"<div style='height:40px;border-radius:8px;border:1px solid var(--line);background:{v}'></div>"
            f"<div class='meta mono' style='font-size:10.5px'>{esc(k)}<br>{esc(v)}</div></div>"
            for k, v in palette_.items() if str(v).startswith("#")
        )
        st.markdown(f"<div>{boxes}</div>", unsafe_allow_html=True)
    st.caption("قلم متن: Vazirmatn · اعداد و شناسه‌ها: IBM Plex Mono · تغییر ظاهر از دکمهٔ پایین ریل راست.")


def _components() -> None:
    _demo("ledger — عدد دفتری", "ledger(120, 'پرونده‌ها', accent='teal')",
          lambda: st.markdown("<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:12px'>"
                              + ledger(120, "پرونده‌ها", accent="teal") + ledger(73, "مواد قانونی", accent="gold")
                              + ledger(9, "در صف بازبینی", accent="red") + ledger(806, "اسناد") + "</div>",
                              unsafe_allow_html=True))
    _demo("stamp — مهر وضعیت", "stamp('مختومه', 'teal')  # gray | teal | gold | review | red",
          lambda: st.markdown(" ".join(stamp(t, k) for t, k in (("در جریان", "gray"), ("مختومه", "teal"),
                                                                    ("استناد ناقص", "gold"), ("ناقص", "review"),
                                                                    ("ناموفق", "red"))), unsafe_allow_html=True))
    _demo("case_id — شمارهٔ پرونده", "case_id('1402009988')",
          lambda: st.markdown(case_id("1402009988") + " " + case_id(""), unsafe_allow_html=True))
    _demo("chips / kv", "chips(['شخص ثالث', 'بازیافت'], teal=True); kv([('مرجع', 'شعبهٔ ۳')])",
          lambda: st.markdown(chips(["شخص ثالث", "بازیافت", "مادهٔ ۳۰"], teal=True)
                              + kv([("مرجع رسیدگی", "دادگاه عمومی حقوقی تهران"), ("رشتهٔ بیمه", "شخص ثالث")]),
                              unsafe_allow_html=True))
    _demo("card / panel", "card('<h4>…</h4>'); panel('عنوان', body, sub='زیرعنوان')",
          lambda: (card("<h4>کارت</h4><div class='meta'>متن توضیحی کوتاه</div>"),
                   panel("پنل", kv([("کلید", "مقدار")]), sub="زیرعنوان")))
    _demo("timeline", "timeline([{'date': '1402/03/12', 'title': 'جلسهٔ اول', 'detail': 'شعبهٔ ۳'}])",
          lambda: st.markdown(timeline([{"date": "1402/03/12", "title": "جلسهٔ اول رسیدگی", "detail": "شعبهٔ ۳"},
                                        {"date": "1402/06/20", "title": "ارجاع به کارشناسی", "detail": ""}]),
                              unsafe_allow_html=True))
    _demo("answer + intent badge", "answer('…'); <span class='intent-badge law'>",
          lambda: (st.markdown(" ".join(f"<span class='intent-badge {k}'>{esc(v)}</span>" for k, v in _INTENT_FA.items()),
                               unsafe_allow_html=True),
                   answer("بیمه‌گر پس از پرداخت خسارت در حدود آن قائم‌مقام بیمه‌گذار می‌شود [1].")))
    _demo("components.row — ردیف قابل‌کلیک", "rowlist_start(); row('عنوان', 'خط دوم', key='k')",
          lambda: (components.rowlist_start(),
                   components.row("بازیافت خسارت پرداختی از رانندهٔ مقصر", "شماره ۱۴۰۲۰۰۹۹۸۸ · مختومه", key="gal_row_1"),
                   components.row("دعوای بازیافت — رانندهٔ فاقد گواهینامه", "شماره ۱۴۰۱۴۸۹۵۹۲ · رد دعوا", key="gal_row_2")))
    _demo("components.citations", "citations(contexts, document_action=False)",
          lambda: components.citations(samples.CONTEXTS, key_prefix="gal"))
    _demo("components.steps_panel / reasoning_panel", "steps_panel(steps); reasoning_panel(text)",
          lambda: (components.steps_panel(samples.STEPS), components.reasoning_panel("مدل ابتدا مادهٔ ۳۰ را خواند…")))
    _demo("components.provenance_panel", "provenance_panel(block)  # از app/rag/provenance.py",
          lambda: components.provenance_panel(samples.PROVENANCE, key_prefix="gal", expanded=True))
    _demo("components.similar_cases_panel", "similar_cases_panel(items, lessons, advice, offset=1)",
          lambda: components.similar_cases_panel([samples.CASE, samples.CASE_2], samples.LESSONS,
                                                  "پرونده‌های ۲ و ۳ نزدیک‌ترین‌اند؛ در ۲ حکم به نفع بیمه‌گر صادر شد [2].",
                                                  key_prefix="gal", offset=1))
    _demo("components.ci_panel", "ci_panel(runs)  # از app/rag/ci.list_ci_runs",
          lambda: components.ci_panel(samples.CI_RUNS))


def _patterns() -> None:
    from app.ui.views.agent import _stepper

    st.markdown("**حباب‌های گفتگو**")
    st.markdown("<div class='bubble-user'>ماده ۳۰ قانون بیمه دربارهٔ جانشینی چه می‌گوید؟</div>", unsafe_allow_html=True)
    answer("بیمه‌گر در حدود خسارتی که پرداخته قائم‌مقام بیمه‌گذار است [1].")
    st.divider()
    st.markdown("**خط لولهٔ ثبت مدخل + دروازهٔ گفتگویی**")
    _stepper(samples.RUN_VIEW)
    st.markdown("<span class='intent-badge archive'>در انتظار پاسخ شما در گفتگو</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='answer'>{esc(samples.CONVERSATION_MESSAGE).replace(chr(10), '<br>')}</div>",
                unsafe_allow_html=True)
    st.caption("پاسخ در همان کادر پایین صفحهٔ دستیار نوشته می‌شود — بدون جدول.")
    st.divider()
    st.markdown("**نمایش ردپای عامل (زنده)**")
    with st.status("عامل در حال پژوهش در آرشیو…", expanded=True, state="complete"):
        st.caption("دور ۱")
        st.markdown("<div class='kv'><span class='k mono'>search_law</span><span>query=ماده ۳۰</span></div>",
                    unsafe_allow_html=True)
        st.caption("✓ search_law(query='ماده ۳۰') → ۳ ماده · ۱۲ میلی‌ثانیه")


def _stages() -> None:
    st.caption("هر مرحله چند پیام آماده دارد؛ «اجرای مرحله» شما را به دستیار می‌برد و پیام‌ها را یکی‌یکی می‌فرستد.")
    for i, stage in enumerate(STAGES, 1):
        with st.container(border=True):
            st.markdown(f"**{fa_num(i)}. {esc(stage.title)}**")
            st.markdown(f"<div class='meta'>{esc(stage.blurb)}</div>", unsafe_allow_html=True)
            for p in stage.prompts:
                tag = "پاسخ" if p.reply else (_INTENT_FA.get(p.intent, "خودکار") if p.intent else "خودکار")
                st.markdown(f"<div class='kv'><span class='k'>{esc(tag)}{' · ' + esc(p.mode) if p.mode else ''}</span>"
                            f"<span>{esc(p.text[:110])}{'…' if len(p.text) > 110 else ''}"
                            f"{'<div class=meta>' + esc(p.note) + '</div>' if p.note else ''}</span></div>",
                            unsafe_allow_html=True)
            cols = st.columns([1, 3])
            if stage.prompts and cols[0].button("اجرای مرحله", key=f"gal_stage_{stage.id}", type="primary",
                                                use_container_width=True):
                st.session_state["stage"] = {"id": stage.id, "step": 0}
                st.session_state["chat"] = []
                st.session_state["view"] = "agent"
                st.rerun()
            if stage.show:
                cols[1].caption("بخش‌های مرتبط: " + "، ".join(stage.show))
    st.caption("اجرای همهٔ مراحل به‌صورت خودکار و بررسی انتظارات: `python -m scripts.demo_stages`")


def render(cfg: dict, state: dict) -> None:
    st.title("نمایشگاه طراحی")
    st.caption("واژگان بصری برنامه روی داده‌های نمونه — و مراحل نمایش برای مشتری.")
    tokens, comps, patterns, stages = st.tabs(["توکن‌ها", "اجزا", "الگوها", "مراحل نمایش"])
    with tokens:
        _tokens()
    with comps:
        _components()
    with patterns:
        _patterns()
    with stages:
        _stages()
    with st.expander("امضای همهٔ کمک‌تابع‌ها"):
        for module, names in ((th, ("card", "panel", "ledger", "stamp", "case_id", "chips", "kv", "timeline", "answer")),
                              (components, ("row", "rowlist_start", "citations", "steps_panel", "reasoning_panel",
                                            "provenance_panel", "similar_cases_panel", "ci_panel", "usage_caption"))):
            for name in names:
                fn = getattr(module, name)
                st.code(f"{name}{inspect.signature(fn)}", language="python")
