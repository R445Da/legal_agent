"""
The archive's visual language, ported from `app/static/app.html`.

The look is a legal ledger, not a dashboard: warm paper (`#F3F0E7`) rather than
cold grey, tan rules rather than blue-grey ones, a dark ink navigation rail with
a gold edge on the active section, IBM Plex Mono for every numeral, dashed
borders standing in for rubber stamps and ledger rules, and a real shadow under
each panel. The tokens below are the originals, unchanged — this file exists so
Streamlit's widgets can be dressed in them.

Components carried over from the original stylesheet, with the same names:

  .ledger-card   a metric: dashed accent rule on top, big mono numeral
  .panel         a titled section: bordered head, quiet body
  .stamp         a status pill, 1.5px dashed in its own colour
  .case-id       a case number, one bordered box per digit
  .folder-tab    the case tabs, drawn as physical file-folder tabs
  .tl-item       the timeline, with a ringed dot per event

Dark mode keeps the same character — the ink navy becomes the page, the cream
becomes the text — rather than switching to a different design.

`fa_num()` is the original `faNum`: every count, date and score goes through it,
because Latin digits in a Persian layout read as a bug.
"""

import streamlit as st

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(value) -> str:
    return str(value if value is not None else "—").translate(_DIGITS)


def fa_ms(ms: float | None) -> str:
    if ms is None:
        return "—"
    return fa_num(f"{ms/1000:.1f}") + " ثانیه" if ms >= 1000 else fa_num(f"{ms:.0f}") + " میلی‌ثانیه"


def esc(text) -> str:
    return (
        str(text if text is not None else "—")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


# Tokens copied verbatim from app/static/app.html.
LIGHT = {
    "ink": "#142236", "inkSoft": "#44506B",
    "paper": "#F3F0E7", "surface": "#FFFFFF",
    "line": "#E1DAC7", "lineSoft": "#EEEADD",
    "stampRed": "#7C2D2D", "stampRedSoft": "#F2E1DC",
    "teal": "#0F4C3A", "tealSoft": "#DCEAE1",
    "amber": "#9C7209", "amberSoft": "#F2E6C9",
    "gray": "#6E6858", "graySoft": "#EAE5D8",
    "gold": "#A9812E", "goldSoft": "#F2E9D3",
    "railBg": "#142236", "railInk": "#C9D0C5", "railDim": "#7C8B80",
    "shadow": "0 1px 2px rgba(20,34,54,.05), 0 8px 24px -10px rgba(20,34,54,.14)",
}

# The same design after dark: the rail's navy becomes the page, paper becomes ink.
DARK = {
    "ink": "#E9E4D7", "inkSoft": "#B9BFCB",
    "paper": "#0E1620", "surface": "#17202C",
    "line": "#2C3949", "lineSoft": "#232F3D",
    "stampRed": "#E7A6A0", "stampRedSoft": "#3A2220",
    "teal": "#7FC9A8", "tealSoft": "#14302A",
    "amber": "#D9AE4B", "amberSoft": "#332813",
    "gray": "#9AA08F", "graySoft": "#212B36",
    "gold": "#D8B25E", "goldSoft": "#332B18",
    "railBg": "#0A111A", "railInk": "#C9D0C5", "railDim": "#7C8B80",
    "shadow": "0 1px 2px rgba(0,0,0,.3), 0 8px 24px -10px rgba(0,0,0,.55)",
}


def current() -> str:
    return st.session_state.setdefault("appearance", "light")


def toggle() -> None:
    st.session_state["appearance"] = "dark" if current() == "light" else "light"


def palette() -> dict:
    return DARK if current() == "dark" else LIGHT


def _css(p: dict) -> str:
    on_teal = "#04201d" if p is DARK else "#ffffff"
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;600;700&display=swap');

:root {{ {''.join(f'--{k}:{v};' for k, v in p.items())} --radius:12px; }}

/* ---------- shell ---------------------------------------------------- */
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stBottom"] {{
  background: var(--paper) !important; color: var(--ink) !important;
}}
* {{ font-family: 'Vazirmatn', Tahoma, sans-serif !important; }}
/* Streamlit's icons are glyphs in an icon font. The blanket font rule above
   would print their code points as words — "keyboard_arrow_down", "check" —
   so every icon element is exempted. Match on the testid *containing* "Icon":
   naming only `stIconMaterial` missed `stExpanderIconCheck`, which is how a
   stray English "check" kept appearing next to expanders. */
[data-testid*="Icon"], [data-testid*="icon"],
.material-icons, .material-symbols-rounded, span[class*="material-symbols"] {{
  font-family: 'Material Symbols Rounded', 'Material Icons' !important;
}}
body, [data-testid="stMain"] {{ font-size: 14.3px; line-height: 1.75; }}

/* Numerals are monospaced — the ledger signature. */
.mono, .ledger-card .num, .nav-item .n, .stamp, .cite, .ctx-num,
.sim-pct, .tl-date, .case-id .d, .step .sms,
[data-testid="stMetricValue"] {{
  font-family: 'IBM Plex Mono', 'Vazirmatn', monospace !important;
}}

/* Keep the header — it is where Streamlit renders the sidebar's » expand
   control. Zeroing its height (an earlier attempt at reclaiming space) deleted
   that button, leaving no way to reopen the panel. Make it transparent instead
   and let it reserve its own room. */
[data-testid="stHeader"] {{ background: transparent !important; }}
[data-testid="stMain"] .block-container {{ max-width: 100% !important; padding: 1rem 1.6rem 3rem !important; }}
[data-testid="stToolbar"] {{ visibility: hidden; }}

/* Two panels, both collapsible, neither across the top, and both driven by the
   same chevron — Streamlit's own sidebar is not used at all, because its
   control disappears from the DOM once collapsed and Python cannot reopen it.

     LEFT  .model-panel — model + retrieval, on the page's own surface
     RIGHT .nav-rail    — the numbered sections, the dark ink rail

   Each is pinned: a percentage width alone collapses a column to a single
   character, and a bare min-width lets flex grow it over the content instead. */
[data-testid="stSidebar"], [data-testid="stExpandSidebarButton"] {{ display: none !important; }}

[data-testid="stColumn"]:has(.nav-rail),
[data-testid="stColumn"]:has(.model-panel) {{
  border-radius: var(--radius); padding: 10px 9px !important;
  box-shadow: var(--shadow);
  flex: 0 0 210px !important; width: 210px !important; min-width: 210px !important;
}}
[data-testid="stColumn"]:has(.nav-rail) {{ background: var(--railBg); }}
[data-testid="stColumn"]:has(.model-panel) {{
  background: var(--surface); border: 1px solid var(--line);
}}
/* Collapsed, a panel leaves nothing behind but a handle. The column itself
   goes to zero width — a narrow leftover strip was the wrong answer — and its
   toggle is lifted out as a grip pinned to the screen edge. */
[data-testid="stColumn"]:has(.nav-rail.shut),
[data-testid="stColumn"]:has(.model-panel.shut) {{
  flex: 0 0 0 !important; width: 0 !important; min-width: 0 !important;
  padding: 0 !important; background: transparent !important;
  border: none !important; box-shadow: none !important; overflow: visible !important;
}}
/* The panel handles. One treatment for both panels and both states — a small
   neutral square, the way the Router lab's sidebar control looks. Open, it sits
   at the top of its panel; collapsed, the same square is pinned to the screen
   edge and is all that remains of the panel. */
.st-key-nav_toggle_open button, .st-key-panel_toggle_open button,
.st-key-nav_toggle_shut button, .st-key-panel_toggle_shut button {{
  width: 30px !important; min-width: 30px !important;
  height: 30px !important; min-height: 30px !important;
  padding: 0 !important; border-radius: 8px !important;
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  box-shadow: none !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
}}
.st-key-nav_toggle_open button p, .st-key-panel_toggle_open button p,
.st-key-nav_toggle_shut button p, .st-key-panel_toggle_shut button p,
.st-key-nav_toggle_open button div, .st-key-panel_toggle_open button div,
.st-key-nav_toggle_shut button div, .st-key-panel_toggle_shut button div {{
  color: var(--ink) !important; font-size: 15px !important; font-weight: 700 !important;
  line-height: 1 !important; text-align: center !important;
}}
.st-key-nav_toggle_open button:hover, .st-key-panel_toggle_open button:hover,
.st-key-nav_toggle_shut button:hover, .st-key-panel_toggle_shut button:hover {{
  border-color: var(--teal) !important;
}}
/* Keep navigation and filter state changes still, so reruns do not look shaky. */
.st-key-nav_toggle_open button, .st-key-panel_toggle_open button,
.st-key-nav_toggle_shut button, .st-key-panel_toggle_shut button,
[data-testid="stExpander"] details, [role="switch"], .stSelectbox,
.stSelectbox *, [data-testid="stChatInput"], [data-testid="stChatInput"] * {{
  transition: none !important; animation: none !important;
}}
/* Collapsed: pinned to the edge, at the same height the open handle sits at —
   not vertically centred on the whole screen. Centring made the same button
   jump from the top of the panel to the middle of the page on every toggle,
   which read as the control breaking rather than as one thing changing state. */
.st-key-nav_toggle_shut button, .st-key-panel_toggle_shut button {{
  position: fixed !important; top: 56px !important; z-index: 1000 !important;
}}
.st-key-nav_toggle_shut button {{ right: 6px !important; }}
.st-key-panel_toggle_shut button {{ left: 6px !important; }}
.st-key-nav_toggle_shut, .st-key-panel_toggle_shut {{ height: 0 !important; overflow: visible !important; }}
/* Open: the square sits flush at the panel's inner edge. */
.st-key-nav_toggle_open, .st-key-panel_toggle_open {{ display: flex; margin-bottom: 6px; }}
.st-key-nav_toggle_open {{ justify-content: flex-start; }}
.st-key-panel_toggle_open {{ justify-content: flex-end; }}
.st-key-nav_toggle_open button, .st-key-panel_toggle_open button {{ width: 30px !important; }}

/* The composer is one native Streamlit control: text and microphone share the
  same supported chat-input lifecycle. */
/* Pinned to the bottom of the content column rather than left to sit wherever
   the message list happens to end. `st.chat_input` only gets Streamlit's own
   fixed bottom bar when it is called at the script's top level; nested in a
   column, as it has to be here to sit beside the two side panels, it renders
   inline instead — so on any conversation taller than one screen it drifted
   down the page and off-screen, and reaching it meant scrolling to find it.
   `sticky` keeps it flush with the column's own width (which `fixed` cannot,
   since that width changes whenever a side panel opens or closes) while still
   settling to the bottom of the viewport once there is enough to scroll. */
.st-key-composer_wrap {{
  position: sticky !important; bottom: 14px; z-index: 20;
  padding-top: 10px;
}}
.st-key-composer_wrap [data-testid="stChatInput"] {{ min-height: 52px !important; }}
.st-key-composer_wrap [data-testid="stChatInput"] textarea {{
  padding: 15px 14px 15px 52px !important; line-height: 1.7 !important;
}}
/* The content column takes whatever is left. Basis 0, not auto: an auto basis
   is measured from the content, which is wider than the space beside two
   pinned rails, and the columns then overlap. */
[data-testid="stColumn"]:has(.content-col) {{
  flex: 1 1 0 !important; width: auto !important; min-width: 0 !important;
}}
.st-key-hidden_panel {{ display: none !important; }}

/* Give the center room to breathe on laptop and browser-preview widths. */
@media (max-width: 980px) {{
  [data-testid="stColumn"]:has(.nav-rail),
  [data-testid="stColumn"]:has(.model-panel) {{
    flex-basis: 174px !important; width: 174px !important; min-width: 174px !important;
  }}
}}
@media (max-width: 720px) {{
  [data-testid="stMain"] .block-container {{ padding-inline: .7rem !important; }}
  [data-testid="stColumn"]:has(.nav-rail),
  [data-testid="stColumn"]:has(.model-panel) {{
    flex-basis: 150px !important; width: 150px !important; min-width: 150px !important;
    padding-inline: 6px !important;
  }}
}}

/* rail items */
[data-testid="stColumn"]:has(.nav-rail) .stButton > button {{
  background: transparent !important; border: none !important;
  border-inline-start: 3px solid transparent !important;
  border-radius: 8px !important; box-shadow: none !important;
  text-align: right !important; padding: 8px 11px !important; margin-bottom: 2px;
  justify-content: flex-start !important;
}}
[data-testid="stColumn"]:has(.nav-rail) .stButton > button p,
[data-testid="stColumn"]:has(.nav-rail) .stButton > button div,
[data-testid="stColumn"]:has(.nav-rail) .stButton > button span {{
  color: var(--railInk) !important; font-size: 13px !important;
  text-align: right !important; width: 100%;
}}
[data-testid="stColumn"]:has(.nav-rail) .stButton > button:hover {{
  background: rgba(255,255,255,.06) !important;
  border-inline-start-color: var(--gold) !important;
}}
[data-testid="stColumn"]:has(.nav-rail) .stButton > button:hover p,
[data-testid="stColumn"]:has(.nav-rail) .stButton > button:hover div,
[data-testid="stColumn"]:has(.nav-rail) .stButton > button:hover span {{ color: #fff !important; }}
[data-testid="stColumn"]:has(.nav-rail) [data-testid="stCaptionContainer"],
[data-testid="stColumn"]:has(.nav-rail) [data-testid="stCaptionContainer"] p {{
  color: var(--railDim) !important;
}}
[data-testid="stColumn"]:has(.nav-rail) hr {{ border-color: rgba(255,255,255,.08) !important; }}

/* both chevrons: the first button in each panel */

/* Column order — and only column order — reads right to left. Putting this on
   the app container instead breaks Streamlit's own width arithmetic. */
[data-testid="stHorizontalBlock"] {{ direction: rtl; }}
[data-testid="stColumn"] {{ direction: ltr; }}

[data-testid="stMain"] h1, [data-testid="stMain"] h2, [data-testid="stMain"] h3,
[data-testid="stMain"] h4, [data-testid="stMain"] p, [data-testid="stMain"] li,
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"],
[data-testid="stMetricLabel"], [data-testid="stWidgetLabel"],
[data-testid="stExpander"] summary, [data-baseweb="tab"] {{ direction: rtl; text-align: right; }}
[data-testid="stMain"] textarea, [data-testid="stMain"] input[type="text"] {{
  direction: rtl !important; text-align: right !important;
}}
pre, code, [data-testid="stJson"], [data-testid="stDataFrame"] {{ direction: ltr; text-align: left; }}

h1 {{ font-size: 19px !important; font-weight: 800 !important; margin-bottom: 2px !important; }}
h2 {{ font-size: 15px !important; font-weight: 700 !important; }}
h3 {{ font-size: 14px !important; font-weight: 700 !important; }}

[data-testid="stMain"], [data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stMetricValue"], [data-testid="stMetricLabel"],
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
[data-baseweb="tab"], [data-testid="stExpander"] summary,
h1, h2, h3, h4, h5, label {{ color: var(--ink) !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
small {{ color: var(--gray) !important; font-size: 12.6px !important; }}
/* Inline Markdown colors are emitted with a dark inline style. Keep them
  readable when the active palette is dark. */
[data-testid="stMain"] .stMarkdownColoredText {{ color: var(--inkSoft) !important; }}

/* ---------- the ink rail --------------------------------------------- */
[data-testid="stSidebar"] {{
  background: var(--railBg); border-radius: var(--radius);
  padding: 12px 10px !important; box-shadow: var(--shadow);
}}
[data-testid="stSidebar"] .stButton > button {{
  background: transparent !important; border: none !important;
  border-inline-start: 3px solid transparent !important;
  border-radius: 8px !important; color: var(--railInk) !important;
  font-size: 13.3px !important; font-weight: 500 !important;
  text-align: right !important; padding: 9px 12px !important; margin-bottom: 3px;
  justify-content: flex-start !important;
}}
/* The label lives in a <p> inside the button, and the global "all text is ink"
   rule reaches it — which painted the rail's items dark navy on dark navy.
   Colour the inner nodes explicitly. */
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button div,
[data-testid="stSidebar"] .stButton > button span {{
  color: var(--railInk) !important; font-size: 13.3px !important;
  text-align: right !important; width: 100%;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
  background: rgba(255,255,255,.06) !important;
  border-inline-start-color: var(--gold) !important;
}}
[data-testid="stSidebar"] .stButton > button:hover p,
[data-testid="stSidebar"] .stButton > button:hover div,
[data-testid="stSidebar"] .stButton > button:hover span {{
  color: #ffffff !important;
}}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,.08) !important; }}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
  color: var(--railDim) !important;
}}
.nav-label {{
  font-size: 10.3px; color: var(--railDim); letter-spacing: .5px;
  padding: 10px 12px 6px; font-family: 'IBM Plex Mono' !important; direction: rtl; text-align: right;
}}
.rail-brand {{
  font-weight: 800; font-size: 14.8px; color: #fff; padding: 8px 12px 2px;
  direction: rtl; text-align: right;
}}
.rail-foot {{
  margin-top: 12px; padding: 10px 12px 2px; border-top: 1px solid rgba(255,255,255,.08);
  font-size: 11px; color: var(--railDim); line-height: 1.9; direction: rtl; text-align: right;
  font-family: 'IBM Plex Mono' !important;
}}
/* the ☰ button */
[data-testid="stSidebar"] .stButton > button[kind="secondary"]:first-child {{
  font-size: 17px !important;
}}
.nav-item {{
  display: flex; align-items: center; gap: 9px; padding: 10px 12px; margin-bottom: 4px;
  border-radius: 9px; font-size: 13.3px; font-weight: 600; direction: rtl;
  background: linear-gradient(90deg, rgba(255,255,255,.13), rgba(255,255,255,.06));
  color: #fff; border: 1px solid rgba(255,255,255,.08);
  border-inline-start: 3px solid var(--gold); box-shadow: 0 5px 14px rgba(0,0,0,.12);
}}
.nav-item .n {{ font-size: 10.5px; color: var(--gold); width: 18px; }}
.nav-badge {{
  margin-inline-start: auto; background: var(--stampRed); color: #fff;
  font-size: 10px; border-radius: 10px; padding: 1px 6px;
  font-family: 'IBM Plex Mono' !important;
}}

/* ---------- ledger cards, panels, stamps ------------------------------ */
.ledger-card {{
  background: var(--surface); border: 1px solid var(--line);
  border-top: 3px dashed var(--line); border-radius: var(--radius);
  padding: 15px 17px; box-shadow: var(--shadow); direction: rtl; text-align: right;
}}
.ledger-card .num {{ font-size: 25px; font-weight: 600; line-height: 1; color: var(--ink); }}
.ledger-card .lbl {{ color: var(--gray); font-size: 12px; margin-top: 8px; }}
.ledger-card.accent-red {{ border-top-color: var(--stampRed); }}
.ledger-card.accent-red .num {{ color: var(--stampRed); }}
.ledger-card.accent-teal {{ border-top-color: var(--teal); }}
.ledger-card.accent-teal .num {{ color: var(--teal); }}
.ledger-card.accent-amber {{ border-top-color: var(--amber); }}
.ledger-card.accent-amber .num {{ color: var(--amber); }}
.ledger-card.accent-gold {{ border-top-color: var(--gold); }}
.ledger-card.accent-gold .num {{ color: var(--gold); }}

.panel {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); margin-bottom: 18px; box-shadow: var(--shadow);
  direction: rtl; text-align: right; overflow: hidden;
}}
.panel-head {{
  padding: 13px 17px; border-bottom: 1px solid var(--line);
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
}}
.panel-head h3 {{ margin: 0; font-size: 14px; font-weight: 700; color: var(--ink); }}
.panel-head .sub {{ font-size: 11.6px; color: var(--gray); }}
.panel-body {{ padding: 10px 17px 14px; }}

.card {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 14px 16px; margin-bottom: 11px;
  box-shadow: var(--shadow); direction: rtl; text-align: right; color: var(--ink);
}}
.card h4 {{ margin: 0 0 5px; font-size: 13.5px; font-weight: 700; color: var(--ink); }}
.card .meta {{ color: var(--gray); font-size: 11.6px; line-height: 1.9; }}
.card.warn {{ background: var(--amberSoft); border-color: var(--amber); border-style: dashed; }}

.stamp {{
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 11px;
  border-radius: 20px; font-size: 11.3px; font-weight: 700;
  border: 1.5px dashed currentColor; white-space: nowrap; margin: 2px 2px 2px 0;
}}
.stamp .dotc {{ width: 6px; height: 6px; border-radius: 50%; background: currentColor; }}
.stamp.teal {{ color: var(--teal); background: var(--tealSoft); }}
.stamp.gray {{ color: var(--gray); background: var(--graySoft); }}
.stamp.review {{ color: var(--amber); background: var(--amberSoft); }}
.stamp.red {{ color: var(--stampRed); background: var(--stampRedSoft); }}

.chip {{
  display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 14px;
  background: var(--graySoft); color: var(--inkSoft); font-size: 11px; font-weight: 600;
  margin: 2px 2px 2px 0;
}}
.chip.teal {{ background: var(--tealSoft); color: var(--teal); }}

.case-id {{ display: inline-flex; gap: 3px; direction: ltr; unicode-bidi: isolate; flex-wrap: wrap; }}
.case-id .d {{
  font-weight: 600; font-size: 12px; min-width: 16px; height: 19px; padding: 0 2px;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--line); border-radius: 2px;
  background: var(--surface); color: var(--inkSoft);
}}
.case-id.none .d {{ border-style: dashed; color: var(--gray); }}

.kv {{
  display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--lineSoft);
  font-size: 12.8px; direction: rtl; text-align: right; color: var(--ink);
}}
.kv:last-child {{ border-bottom: none; }}
.kv .k {{ color: var(--gray); min-width: 8.5rem; flex-shrink: 0; font-size: 11.8px; }}

/* timeline */
.tl-item {{ display: flex; gap: 14px; position: relative; padding-bottom: 20px; direction: rtl; }}
.tl-item::before {{
  content: ""; position: absolute; top: 22px; bottom: -4px;
  inset-inline-start: 14.5px; width: 1px; background: var(--line);
}}
.tl-item:last-child {{ padding-bottom: 0; }}
.tl-item:last-child::before {{ display: none; }}
.tl-dot {{
  width: 30px; height: 30px; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid var(--teal); color: var(--teal); background: var(--tealSoft);
  font-size: 13px; z-index: 1;
}}
.tl-date {{ font-size: 11.3px; color: var(--gray); }}
.tl-title {{ font-weight: 700; font-size: 13.3px; color: var(--ink); }}
.tl-src {{ color: var(--gray); font-size: 10.8px; margin-top: 4px; }}

/* the entry-build pipeline (app/rag/workflow.py) — the ingest stepper of app.html */
.wf-step {{
  display: flex; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--line);
  direction: rtl;
}}
.wf-step:last-child {{ border-bottom: none; }}
.wf-step.pending {{ opacity: .45; }}
.wf-icon {{
  width: 26px; height: 26px; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid var(--line); color: var(--gray);
  font-family: 'IBM Plex Mono', 'Vazirmatn', monospace; font-size: 11.5px;
}}
.wf-step.running .wf-icon, .wf-step.awaiting_input .wf-icon {{
  border-color: var(--amber); color: var(--amber); background: var(--amberSoft);
}}
.wf-step.done .wf-icon {{ background: var(--teal); color: #fff; border-color: var(--teal); }}
.wf-step.failed .wf-icon {{ background: var(--stampRed); color: #fff; border-color: var(--stampRed); }}
.wf-label {{ font-weight: 600; font-size: 13px; color: var(--ink); }}
.wf-detail {{ font-size: 11.6px; color: var(--inkSoft); margin-top: 2px; }}
.wf-detail.err {{ color: var(--stampRed); }}
.wf-ms {{ font-family: 'IBM Plex Mono', 'Vazirmatn', monospace; font-size: 10.3px; color: var(--gray); }}

/* answers and citations */
/* Same surface + shadow as .card and .panel — every other block on the page
   sits on a raised white card, but this one used the page's own paper colour
   with no shadow, so while an answer is still streaming in (a character or
   two, no visible border at that size) the text reads as loose on the page
   instead of inside a box that just hasn't filled up yet. */
.answer {{
  background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
  padding: 15px 17px; font-size: 13.8px; line-height: 2; white-space: pre-wrap;
  direction: rtl; text-align: right; color: var(--ink); box-shadow: var(--shadow);
}}
.cite {{
  display: inline-flex; min-width: 18px; height: 18px; padding: 0 4px;
  align-items: center; justify-content: center; background: var(--tealSoft);
  color: var(--teal); border-radius: 4px; font-size: 11px; font-weight: 700;
}}
.bar-track {{ height: 6px; border-radius: 4px; background: var(--graySoft); overflow: hidden; }}
.bar-fill {{ height: 100%; background: var(--teal); border-radius: 4px; }}

/* ---------- Streamlit widgets, dressed ------------------------------- */
.stButton > button, [data-testid="stBaseButton-secondary"] {{
  border: 1px solid var(--line) !important; background: var(--surface) !important;
  color: var(--ink) !important; border-radius: 8px !important;
  font-size: 12.6px !important; font-weight: 600 !important;
  padding: 8px 14px !important; height: auto !important; min-height: 2.1rem;
  box-shadow: none !important;
}}
.stButton > button:hover {{ border-color: var(--teal) !important; color: var(--teal) !important; }}
.stButton > button[kind="primary"], [data-testid="stBaseButton-primary"] {{
  background: var(--teal) !important; border-color: var(--teal) !important;
  color: {on_teal} !important;
}}
.stButton > button p, .stButton > button div {{
  white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; line-height: 1.6;
}}

/* ---------- chat ------------------------------------------------------ */
[data-testid="stChatMessage"] {{
  background: transparent !important; direction: rtl; padding: 2px 0 !important;
}}
.bubble-user {{
  background: var(--ink); color: var(--paper);
  padding: 11px 15px; border-radius: 16px 16px 5px 16px;
  display: inline-block; max-width: 88%; line-height: 1.9; font-size: 13.5px;
  direction: rtl; text-align: right;
}}
.intent-badge {{
  display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 14px;
  font-size: 11px; font-weight: 700; border: 1.5px solid currentColor; margin-bottom: 8px;
}}
.intent-badge.query {{ color: var(--teal); background: var(--tealSoft); }}
.intent-badge.archive {{ color: var(--amber); background: var(--amberSoft); }}
.intent-badge.analytics {{ color: var(--inkSoft); background: var(--graySoft); }}
.intent-badge.chat {{ color: var(--teal); background: transparent; border-style: dotted; }}
.intent-badge.unclear {{ color: var(--stampRed); background: var(--stampRedSoft); }}
.thinking {{
  font-size: 12px; color: var(--gray); background: var(--paper);
  border: 1px dashed var(--line); border-radius: 8px; padding: 8px 11px;
  margin-bottom: 8px; direction: rtl; text-align: right; white-space: pre-wrap;
  max-height: 190px; overflow: auto;
}}
.thinking summary {{ cursor: pointer; font-weight: 600; color: var(--inkSoft); }}
.suggest-label {{
  font-size: 10.3px; letter-spacing: .5px; color: var(--gray);
  font-family: 'IBM Plex Mono' !important; direction: rtl; text-align: right; padding-bottom: 4px;
}}
/* The composer: mic and text box read as one control. */
[data-testid="stChatInput"] {{
  background: var(--surface) !important; border: 1px solid var(--line) !important;
  border-radius: 18px !important; box-shadow: 0 7px 22px -10px rgba(20,34,54,.45);
  transition: border-color .18s ease, box-shadow .18s ease;
}}
[data-testid="stChatInput"]:focus-within {{
  border-color: var(--teal) !important;
  box-shadow: 0 0 0 3px var(--tealSoft), 0 9px 25px -12px rgba(15,76,58,.55);
}}
[data-testid="stChatInput"] textarea {{
  direction: rtl !important; text-align: right !important;
  background: transparent !important; font-size: 13.8px !important;
  min-height: 52px !important; padding: 14px 15px 14px 58px !important;
}}
[data-testid="stAudioInput"] {{
  background: var(--tealSoft) !important; border: 1px solid var(--teal) !important;
  border-radius: 50% !important; box-shadow: 0 3px 10px -5px rgba(15,76,58,.7);
}}
.st-key-composer_wrap [data-testid="stAudioInputActionButton"] {{
  border-radius: 50% !important; background: var(--tealSoft) !important;
  transition: background .18s ease, transform .18s ease;
}}
.st-key-composer_wrap [data-testid="stAudioInputActionButton"]:hover {{
  background: var(--teal) !important; transform: scale(1.06);
}}
.st-key-composer_wrap [data-testid="stAudioInputActionButton"]:hover svg {{ fill: #fff !important; }}

/* Search fields are quiet controls, but should still read as a deliberate tool. */
[data-testid="stTextInput"] {{
  background: var(--surface) !important; border: 1px solid var(--line) !important;
  border-radius: 10px !important; padding: 2px 8px !important;
  box-shadow: 0 4px 14px -10px rgba(20,34,54,.55);
}}
[data-testid="stTextInput"] [data-baseweb="input"] {{
  border: none !important; background: transparent !important; box-shadow: none !important;
}}
[data-testid="stTextInput"] input {{
  min-height: 38px !important; padding: 7px 8px !important; font-size: 13.2px !important;
}}
[data-testid="stTextInput"]:focus-within {{
  border-color: var(--teal) !important;
  box-shadow: 0 0 0 3px var(--tealSoft), 0 7px 18px -12px rgba(15,76,58,.55);
}}
[data-testid="stExpander"]:has([data-testid="stTextInput"]) {{
  border-color: var(--line) !important; background: color-mix(in srgb, var(--surface) 72%, var(--paper)) !important;
}}

/* ---------- clickable record rows ------------------------------------ */
/* A list where the row itself is the control — no «مشاهده» button beside it,
   which also keeps every row flush to the same right and left edges. */
.rowlist ~ div .stButton > button,
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .rowlist) .stButton > button {{
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: var(--radius) !important;
  box-shadow: var(--shadow) !important;
  padding: 13px 16px !important;
  margin-bottom: 9px;
  text-align: right !important;
  align-items: flex-start !important;
  justify-content: flex-start !important;
}}
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .rowlist) .stButton > button:hover {{
  border-color: var(--teal) !important;
  box-shadow: 0 2px 4px rgba(20,34,54,.06), 0 10px 26px -12px rgba(15,76,58,.35) !important;
}}
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .rowlist) .stButton > button p,
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .rowlist) .stButton > button div {{
  direction: rtl !important; text-align: right !important;
  width: 100% !important; display: block !important;
  font-size: 12.4px !important; line-height: 1.95 !important; font-weight: 400 !important;
}}
/* the first line is the record's title, and has to read as one */
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .rowlist) .stButton > button p strong {{
  font-size: 13.8px !important; font-weight: 700 !important; color: var(--ink) !important;
  line-height: 2.3;
}}
/* Streamlit centres a button's contents; a record row must start at the edge. */
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .rowlist) .stButton > button > div {{
  width: 100% !important; align-items: flex-start !important;
  justify-content: flex-start !important; text-align: right !important;
}}

[data-testid="stMetric"] {{
  background: var(--surface) !important; border: 1px solid var(--line);
  border-top: 3px dashed var(--line); border-radius: var(--radius);
  padding: 14px 16px; box-shadow: var(--shadow); overflow: visible;
}}
[data-testid="stMetricValue"] {{
  font-size: 25px !important; font-weight: 600 !important; line-height: 1 !important;
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
  direction: rtl;
}}
[data-testid="stMetricLabel"] {{
  color: var(--gray) !important; font-size: 12px !important; white-space: normal !important;
}}

[data-testid="stExpander"] details {{
  background: var(--surface) !important; border: 1px solid var(--line) !important;
  border-radius: 8px !important; box-shadow: none !important;
}}
[data-testid="stExpander"] summary {{
  background: var(--paper) !important; font-size: 12px !important; font-weight: 600 !important;
  color: var(--inkSoft) !important;
}}

input, textarea, select, [data-baseweb="select"] > div, [data-baseweb="input"],
[data-baseweb="textarea"], [data-testid="stFileUploaderDropzone"] {{
  background: var(--surface) !important; color: var(--ink) !important;
  border-color: var(--line) !important; border-radius: 8px !important;
  font-size: 13px !important;
}}
input:focus, textarea:focus {{ border-color: var(--teal) !important; }}
[data-baseweb="popover"] li {{ background: var(--surface) !important; color: var(--ink) !important; }}

/* Keep React-Aria selects at one height; changing a choice must not make the
   panel jump or leave its arrow with the wrong theme colour. */
[data-testid="stSelectbox"] [role="group"], .stSelectbox [role="group"] {{
  min-height: 40px !important; height: 40px !important;
  background: var(--surface) !important; border: 1px solid var(--line) !important;
  border-radius: 8px !important; overflow: hidden;
}}
[data-testid="stSelectbox"] [role="group"] input, .stSelectbox [role="group"] input {{
  height: 38px !important; min-height: 38px !important;
  background: var(--surface) !important; color: var(--ink) !important;
  border: none !important; padding-inline: 10px !important;
}}
[data-testid="stSelectbox"] [role="group"] > button, .stSelectbox [role="group"] > button {{
  height: 38px !important; min-height: 38px !important;
  color: var(--inkSoft) !important; background: var(--surface) !important;
}}
[data-testid="stSelectbox"] [role="group"] > button:hover, .stSelectbox [role="group"] > button:hover {{
  color: var(--teal) !important; background: var(--tealSoft) !important;
}}
[data-testid="stSelectbox"] button[aria-label="Open"], .stSelectbox button[aria-label="Open"] {{
  height: 38px !important; min-height: 38px !important;
  color: var(--inkSoft) !important; background: var(--surface) !important;
}}
[data-testid="stSelectbox"] button[aria-label="Open"] svg, .stSelectbox button[aria-label="Open"] svg {{
  color: var(--inkSoft) !important; fill: var(--inkSoft) !important;
}}
[data-testid="stSelectbox"] button[aria-label="Open"]:hover,
[data-testid="stSelectbox"] button[aria-label="Open"]:hover svg,
.stSelectbox button[aria-label="Open"]:hover,
.stSelectbox button[aria-label="Open"]:hover svg {{
  color: var(--teal) !important; fill: var(--teal) !important;
}}
[data-testid="stSelectbox"]:focus-within [role="group"], .stSelectbox:focus-within [role="group"] {{
  border-color: var(--teal) !important;
  box-shadow: 0 0 0 3px var(--tealSoft) !important;
}}

/* Toggles retain their footprint and use the same semantic colours in both
   palettes, instead of inheriting the page's dark ink for the switch track. */
[data-testid="stElementContainer"]:has([role="switch"]) {{
  min-height: 42px !important; padding: 6px 0 !important;
}}
[role="switch"] + div, [role="switch"] ~ div {{
  min-height: 30px !important; display: flex !important; align-items: center !important;
  gap: 10px !important; color: var(--ink) !important;
}}
[role="switch"] {{
  width: 42px !important; height: 24px !important; min-width: 42px !important;
  min-height: 24px !important; padding: 0 !important;
  border: 1px solid var(--line) !important; border-radius: 999px !important;
  background: var(--graySoft) !important; box-shadow: inset 0 0 0 1px rgba(20,34,54,.06) !important;
}}
[role="switch"]::after {{
  width: 18px !important; height: 18px !important; margin: 2px !important;
  background: var(--surface) !important; border-radius: 50% !important;
  box-shadow: 0 1px 3px rgba(20,34,54,.25) !important;
}}
[role="switch"][aria-checked="true"] {{
  background: var(--teal) !important; border-color: var(--teal) !important;
}}
[role="switch"][aria-checked="true"]::after {{
  transform: translateX(18px) !important;
}}

[data-testid="stTabs"] [data-baseweb="tab-list"] {{
  gap: 2px; direction: rtl; border-bottom: 1px solid var(--line); background: transparent;
}}
[data-baseweb="tab"] {{
  padding: 9px 15px !important; font-size: 12.6px !important; font-weight: 600 !important;
  color: var(--gray) !important; border-radius: 8px 8px 0 0 !important;
}}
[data-baseweb="tab"][aria-selected="true"] {{
  color: var(--ink) !important; background: var(--surface) !important;
  border: 1px solid var(--line) !important; border-bottom-color: var(--surface) !important;
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background: var(--teal) !important; }}

[data-testid="stDataFrame"] {{ border: 1px solid var(--line); border-radius: 8px; }}
[data-baseweb="slider"] [role="slider"] {{ background: var(--teal) !important; }}
hr {{ border-color: var(--line) !important; }}
.st-key-hidden_panel {{ display: none !important; }}
[data-testid="stColumn"]:has(.panel-title) > div,
[data-testid="stSidebar"] > div {{
  position: sticky; top: .5rem; max-height: calc(100vh - 1.5rem); overflow-y: auto;
}}
.panel-title {{
  font-size: 10.3px; letter-spacing: .5px; color: var(--gray);
  font-family: 'IBM Plex Mono' !important; padding: 2px 4px 8px;
  direction: rtl; text-align: right;
}}
</style>
"""


def apply() -> None:
    st.markdown(_css(palette()), unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Component helpers — the same vocabulary the original stylesheet used.
# --------------------------------------------------------------------------- #
def card(body: str, *, warn: bool = False) -> None:
    st.markdown(f"<div class='card{' warn' if warn else ''}'>{body}</div>", unsafe_allow_html=True)


def panel(title: str, body: str, *, sub: str = "") -> None:
    st.markdown(
        f"<div class='panel'><div class='panel-head'><h3>{esc(title)}</h3>"
        + (f"<span class='sub'>{esc(sub)}</span>" if sub else "")
        + f"</div><div class='panel-body'>{body}</div></div>",
        unsafe_allow_html=True,
    )


def ledger(value, label: str, *, accent: str = "") -> str:
    """A metric in the ledger style: dashed accent rule, big mono numeral."""
    cls = f"ledger-card accent-{accent}" if accent else "ledger-card"
    return f"<div class='{cls}'><div class='num'>{fa_num(value)}</div><div class='lbl'>{esc(label)}</div></div>"


def stamp(text: str, kind: str = "gray") -> str:
    return f"<span class='stamp {kind}'><span class='dotc'></span>{esc(text)}</span>"


def case_id(number) -> str:
    """A case number as one bordered box per digit, as on a paper file."""
    text = str(number or "").strip()
    if not text:
        return "<span class='case-id none'>" + "".join("<span class='d'>—</span>" for _ in range(4)) + "</span>"
    return "<span class='case-id'>" + "".join(
        f"<span class='d'>{esc(ch)}</span>" for ch in fa_num(text)
    ) + "</span>"


def chips(values, *, teal: bool = False) -> str:
    if not values:
        return "<span class='meta'>—</span>"
    cls = "chip teal" if teal else "chip"
    return "".join(f"<span class='{cls}'>{esc(v)}</span>" for v in values)


def kv(pairs: list[tuple[str, str]]) -> str:
    return "".join(
        f"<div class='kv'><span class='k'>{esc(k)}</span><span>{esc(v)}</span></div>"
        for k, v in pairs
    )


def timeline(events: list[dict]) -> str:
    """events: [{date, title, detail}]"""
    out = ""
    for event in events:
        out += (
            "<div class='tl-item'><div class='tl-dot'>◆</div><div>"
            f"<div class='tl-date'>{fa_num(event.get('date'))}</div>"
            f"<div class='tl-title'>{esc(event.get('title'))}</div>"
            + (f"<div class='tl-src'>{esc(event.get('detail'))}</div>" if event.get("detail") else "")
            + "</div></div>"
        )
    return out or "<div class='meta'>رویدادی ثبت نشده است.</div>"


def answer(text: str) -> None:
    st.markdown(f"<div class='answer'>{esc(text)}</div>", unsafe_allow_html=True)
