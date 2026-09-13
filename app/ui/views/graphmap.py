"""۲۰ نقشهٔ دانش — the archive as an Obsidian-style graph.

The nodes are the notes under `آرشیو/` in the user's vault, and the edges are
the `[[wikilinks]]` between them, so this screen and Obsidian's own graph view
draw the same files. Obsidian is a desktop application with no web build and
cannot be embedded in a page; this is the in-app rendering of the same data,
and every node carries an `obsidian://` link for opening the real thing.

The vault is gitignored, so CI, the Docker image and a fresh clone have no
notes at all. Rendering an empty state rather than raising is therefore a
requirement, not a nicety — `scripts/ui_smoke.py` renders every section.
"""

import streamlit as st

from app.rag import vaultmap, vaultsync
from app.ui import aio, components, data, graphcomp, nav, theme
from app.ui.resources import session
from app.ui.theme import esc, fa_num

_KIND_FA = {"case": "پرونده", "law": "قانون", "person": "شخص", "org": "سازمان", "entry": "مدخل"}


@st.cache_data(ttl=60, show_spinner="در حال خواندن والت…")
def _vault() -> dict:
    return vaultmap.load()


data.register_clearer(_vault.clear)


async def _export() -> dict:
    async with session() as s:
        return await vaultsync.export_all(s)


def highlight(names: list[str]) -> None:
    """Mark the notes a tool just touched, so the next render pulses them.

    The agent view calls this as a run progresses; the ring is drawn by
    `graph.js`, which is why a live tool call is visible here at all.
    """
    st.session_state["graph_highlight"] = list(dict.fromkeys(names))[:40]


def highlight_for(terms: list[str]) -> list[str]:
    """Resolve what the tools reported — titles, case numbers, record ids — to
    note names, and mark those.

    The agent's evidence names records, not files, so some resolution step is
    unavoidable; doing it here keeps `agent.py` from having to know that a
    vault exists at all. A term that matches nothing is simply dropped, which
    is the right behaviour when the vault has not been exported yet.
    """
    if not vaultsync.vault_exists():
        return []
    try:
        nodes = _vault()["nodes"]
    except Exception:  # noqa: BLE001 — a graph that cannot load must not break a run
        return []

    found: list[str] = []
    for term in terms:
        needle = str(term or "").strip()
        if not needle:
            continue
        for node in nodes:
            if needle in (node["name"], node["record_id"], node["case_number"]) or (
                len(needle) > 3 and needle in node["name"]
            ):
                found.append(node["name"])
                break
    highlight(found)
    return found


def _open(node: dict) -> None:
    """A node is a record — open it where that record lives."""
    kind, record = node.get("kind"), node.get("record_id") or node.get("name")
    if kind == "case":
        nav.go("cases", open_case=node.get("case_number") or record)
    elif kind in ("person", "org"):
        nav.go("entities", open_entity={"kind": kind, "key": record})
    elif kind == "law":
        nav.go("laws", open_law=record)
    else:
        nav.go("documents", open_doc=record)


def _empty_state() -> None:
    theme.panel(
        "والت اوبسیدین ساخته نشده است",
        "<p>این بخش یادداشت‌های پوشهٔ <code>آرشیو/</code> را در والت شما می‌خواند. "
        "هنوز چنین پوشه‌ای وجود ندارد.</p>"
        "<p>برای ساختن آن، یک بار این دستور را اجرا کنید — فقط داخل "
        "<code>آرشیو/</code> می‌نویسد و به تنظیمات و یادداشت‌های موجود دست نمی‌زند:</p>"
        "<pre style='direction:ltr;text-align:left'>python -m scripts.export_vault --watch</pre>",
        sub=f"مسیر والت: {esc(vaultsync.vault_path())}",
    )


def render(cfg: dict, state: dict) -> None:
    st.title("نقشهٔ دانش")
    st.caption(
        "همان یادداشت‌هایی که در اوبسیدین می‌بینید: رنگ از برچسب می‌آید، شکل از نوع رکورد، "
        "و اندازه از شمار پیوندها. با کلیک، رکورد باز می‌شود؛ با دوبار کلیک، یادداشت در اوبسیدین."
    )

    if not vaultsync.vault_exists():
        _empty_state()
        return

    graph = _vault()
    if not graph["nodes"]:
        _empty_state()
        left, right = st.columns([1, 3])
        if left.button("ساختن یادداشت‌ها", type="primary", use_container_width=True):
            with st.spinner("در حال نوشتن یادداشت‌ها…"):
                result = aio.run(_export())
            data.refresh()
            st.success(f"{fa_num(result['notes'])} یادداشت نوشته شد.")
            st.rerun()
        return

    counts: dict[str, int] = {}
    for node in graph["nodes"]:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1

    cols = st.columns(5)
    cols[0].metric("گره‌ها", fa_num(len(graph["nodes"])))
    cols[1].metric("پیوندها", fa_num(len(graph["edges"])))
    cols[2].metric("برچسب‌ها", fa_num(len(graph["tags"])))
    cols[3].metric("پرونده‌ها", fa_num(counts.get("case", 0)))
    cols[4].metric("قوانین", fa_num(counts.get("law", 0)))

    touched = st.session_state.get("graph_highlight") or []
    if touched:
        st.caption("حلقهٔ قرمز: گره‌هایی که عامل در آخرین اجرا لمس کرده است — "
                   + esc("، ".join(touched[:6])))

    click = graphcomp.graph(graph, palette=theme.palette(), highlight=touched)

    # The component reports the last click with a timestamp; comparing it to
    # the one already handled is what stops a rerun from re-opening the same
    # record every time the script runs again.
    if isinstance(click, dict) and click.get("node"):
        if st.session_state.get("graph_click_at") != click.get("at"):
            st.session_state["graph_click_at"] = click.get("at")
            node = next((n for n in graph["nodes"] if n["name"] == click["node"]), None)
            if node:
                _open(node)

    st.divider()
    left, mid, right = st.columns([1, 1, 2])
    if left.button("هم‌گام‌سازی با پایگاه داده", use_container_width=True):
        with st.spinner("در حال نوشتن یادداشت‌ها…"):
            result = aio.run(_export())
        data.refresh()
        st.success(f"{fa_num(result['written'])} یادداشت به‌روز شد.")
        st.rerun()
    if mid.button("پاک کردن حلقه‌ها", use_container_width=True, disabled=not touched):
        st.session_state["graph_highlight"] = []
        st.rerun()
    right.caption(f"والت: {esc(vaultsync.vault_path())}")

    with st.expander("پرتکرارترین گره‌ها", expanded=False):
        top = sorted(graph["nodes"], key=lambda n: -n["degree"])[:20]
        components.rowlist_start()
        for node in top:
            label = f"{_KIND_FA.get(node['kind'], node['kind'])} · {fa_num(node['degree'])} پیوند"
            if components.row(node["name"], label, key=f"gm_{node['name']}"):
                _open(node)
