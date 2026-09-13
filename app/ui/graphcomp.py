"""
The graph canvas as a real Streamlit component.

`components.html` would have been less code, but it is one-way: an iframe can
show the graph and never tell Python which node was clicked. The alternatives
were both bad — navigating the parent frame reloads the whole app and drops the
session (the model choice, the chat, the open workflow run), and a click that
does nothing is not a graph view. `declare_component(path=…)` is bidirectional
and still needs no build step: the directory is served as-is and `graph.js`
speaks the component protocol by hand.
"""

from __future__ import annotations

import pathlib

import streamlit.components.v1 as components

_DIR = pathlib.Path(__file__).resolve().parent / "static" / "graph"

_render = components.declare_component("legal_vault_graph", path=str(_DIR))


def graph(data: dict, *, palette: dict, highlight: list[str] | None = None, key: str = "vault_graph"):
    """Draw the graph; return `{"node": name, "at": ms}` for the last click.

    `highlight` is the set of note names the agent's tools have just touched —
    they get a breathing ring, which is how a live run shows up on the graph.
    """
    return _render(
        data=data,
        palette=palette,
        highlight=highlight or [],
        key=key,
        default=None,
    )
