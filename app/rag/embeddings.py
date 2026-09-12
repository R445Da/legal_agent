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
import threading
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


class _HashEmbedder:
    """Offline fallback: feature-hashed character n-grams, L2-normalised.

    Selected with `EMBEDDING_MODEL=hash://<dim>` (e.g. `hash://384`). It needs
    no download — Hugging Face and the Qdrant mirror are unreachable from many
    networks this runs on (Iran, locked-down sandboxes) — and it is
    deterministic, so a seeded corpus embeds the same way everywhere. Quality is
    lexical (shared word pieces, not meaning); hybrid retrieval's FTS half and
    the reranker do the rest. Swap to a real model with `scripts.reembed` once
    one is reachable.
    """

    _NGRAMS = (3, 4, 5)

    def __init__(self, dim: int):
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        import hashlib
        import math

        from app.rag.textnorm import normalize_fa

        vec = [0.0] * self.dim
        words = normalize_fa(text or "").split()
        for word in words:
            padded = f" {word} "
            grams = [padded[i:i + n] for n in self._NGRAMS for i in range(max(1, len(padded) - n + 1))]
            grams.append(f"W:{word}")   # whole-word feature, weighted higher
            for gram in grams:
                digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[index] += sign * (2.0 if gram.startswith("W:") else 1.0)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts):
        import numpy as np

        for text in texts:
            yield np.asarray(self._vector(text), dtype="float32")


_LOAD_LOCK = threading.Lock()


def _model():
    # lru_cache alone does not serialise concurrent first calls; three requests
    # arriving on a cold server each started their own 235 MB download.
    with _LOAD_LOCK:
        return _load_model()


@functools.lru_cache(maxsize=1)
def _load_model():
    name = settings.embedding_model
    if name.startswith("hash://"):
        from app.db.models import EMBEDDING_DIM

        dim = int(name.split("://", 1)[1] or EMBEDDING_DIM)
        return _HashEmbedder(dim)

    from fastembed import TextEmbedding

    Path(_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    return TextEmbedding(model_name=name, cache_dir=_CACHE_DIR)


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
