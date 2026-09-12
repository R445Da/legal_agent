"""
Cross-encoder re-ranking.

The retriever's first stage (vector + lexical, fused) is a fast, recall-oriented
filter — it casts a wide net. A cross-encoder then reads each (query, chunk) pair
*together* and scores true relevance, which a bi-encoder embedding can't do
because it never sees the two texts at the same time. This is the single biggest
precision lever in the pipeline — and the single biggest latency cost, because
it runs one forward pass per candidate on CPU.

Two dials control that cost, and they multiply:
  * how many candidates it reads   (RERANK_TOP — linear in latency)
  * how big the model is           (RERANK_MODEL — see CHOICES below)

Runs on fastembed (ONNX, CPU, no torch). Disable entirely with RERANK=0.
`rerank_scores` takes per-call overrides for all three so the UI can A/B them
against `scripts/eval.py` numbers without an .env edit and a restart.
"""

import asyncio
import functools
import math
import os

_MODEL_NAME = os.environ.get("RERANK_MODEL", "jinaai/jina-reranker-v2-base-multilingual")
_ENABLED = os.environ.get("RERANK", "1") != "0"

# Rerankers worth offering in the UI, cheapest first. The multilingual models
# are the only correct choice for Persian; the ms-marco ones are English-trained
# and are here as a speed floor for measuring how much the reranker costs.
CHOICES: list[tuple[str, str]] = [
    ("Xenova/ms-marco-MiniLM-L-6-v2", "MiniLM-L6 · tiny, English — speed floor"),
    ("jinaai/jina-reranker-v1-tiny-en", "Jina v1 tiny · English"),
    ("jinaai/jina-reranker-v2-base-multilingual", "Jina v2 base · multilingual (Persian) — default"),
    ("BAAI/bge-reranker-base", "BGE base · multilingual"),
]


def enabled() -> bool:
    return _ENABLED


def default_model() -> str:
    return _MODEL_NAME


@functools.lru_cache(maxsize=4)
def load_model(model_name: str | None = None):
    """The cross-encoder, cached per model name so the UI can switch between a
    couple without paying the load cost twice."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model_name or _MODEL_NAME)


def _model():
    return load_model(_MODEL_NAME)


def _sigmoid(x: float) -> float:
    # jina rerankers emit logits; squash to a 0..1 relevance so callers can keep
    # treating the number as a similarity (and 1 - score as a distance).
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


async def rerank_scores(
    query: str,
    passages: list[str],
    *,
    enabled: bool | None = None,
    model: str | None = None,
) -> list[float] | None:
    """Relevance in [0, 1] for each passage, aligned to the input order.
    Returns None when re-ranking is disabled or there is nothing to score.

    `enabled` and `model` override the RERANK / RERANK_MODEL env defaults for a
    single call — that is how the retrieval lab A/Bs the reranker live.
    """
    on = _ENABLED if enabled is None else enabled
    if not on or not passages:
        return None
    encoder = load_model(model or _MODEL_NAME)
    raw = await asyncio.to_thread(lambda: list(encoder.rerank(query, passages)))
    return [_sigmoid(float(s)) for s in raw]
