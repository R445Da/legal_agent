"""
Embedding model wrapper.

Uses fastembed (ONNX, CPU, no torch) so the prototype runs offline after
the model downloads once. Swap the model via the EMBEDDING_MODEL env var —
remember to set EMBEDDING_DIM to match and re-ingest, since existing
vectors won't be comparable.

The default is a multilingual model (`intfloat/multilingual-e5-large`,
1024-dim) so Farsi/Persian text retrieves well. e5 models are trained with
asymmetric prefixes — "query: " on the search text, "passage: " on stored
text — so we add them here. A model that doesn't use prefixes (e.g. the
`paraphrase-multilingual-*` family) simply ignores the extra tokens, but
if you switch to one you can set EMBEDDING_PREFIXES=0 to skip them.
"""

import asyncio
import functools
import os
from pathlib import Path

# HuggingFace's Xet/CAS transfer backend throws "CAS Client Error: error
# decoding response body" on some networks, which wedges the model download.
# Plain HTTPS (the LFS path) is slower but reliable. Set before any hf import.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from app.config import settings

_USE_PREFIXES = os.environ.get("EMBEDDING_PREFIXES", "1") != "0"

# fastembed defaults to `{tempfile.gettempdir()}/fastembed_cache` — i.e. /tmp,
# which many Linux setups wipe on reboot/suspend. Losing it mid-session makes
# every embed call block on a ~470 MB re-download. Pin it somewhere persistent.
_CACHE_DIR = os.environ.get("FASTEMBED_CACHE_DIR") or str(Path.home() / ".cache" / "fastembed")


@functools.lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    Path(_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=settings.embedding_model, cache_dir=_CACHE_DIR)


def _prefixed(texts: list[str], kind: str) -> list[str]:
    if not _USE_PREFIXES:
        return list(texts)
    return [f"{kind}: {t}" for t in texts]


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Synchronous batch embedding for stored documents (ingestion path)."""
    prepared = _prefixed(list(texts), "passage")
    return [vec.tolist() for vec in _model().embed(prepared)]


# Back-compat alias — older callers used this name for document embedding.
embed_texts = embed_passages


async def embed_query(text: str) -> list[float]:
    """Async single embedding for a search query (request path)."""
    prepared = _prefixed([text], "query")
    vectors = await asyncio.to_thread(
        lambda: [v.tolist() for v in _model().embed(prepared)]
    )
    return vectors[0]
