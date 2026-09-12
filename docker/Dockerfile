# syntax=docker/dockerfile:1
#
# Legal RAG — single application image.
#
#   * the Streamlit app (streamlit_app.py) — the interface, served on :8501
#   * PostgreSQL 16 + pgvector, embedded in-process via the `pgserver` wheel —
#     no separate database container
#   * fastembed ONNX models baked in (MiniLM embeddings + jina multilingual
#     reranker) so retrieval works with no network
#   * a seed database (docker/seed.dump) restored on first start
#
# The chat LLM is NOT in the image — the app calls Groq (or any configured
# provider) over HTTPS. Set GROQ_API_KEY at run time. Build context is the repo
# root (legal-rag-ui-workbench/).

# ----------------------------------------------------------------------------- #
# builder: resolve and install the Python environment
# ----------------------------------------------------------------------------- #
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# ----------------------------------------------------------------------------- #
# runtime
# ----------------------------------------------------------------------------- #
FROM python:3.12-slim AS runtime

# curl -> HEALTHCHECK ; libgomp1 -> onnxruntime
RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# initdb / postgres refuse to run as a UID with no /etc/passwd entry.
RUN useradd --create-home --uid 1000 app

COPY --from=builder --chown=app:app /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    FASTEMBED_CACHE_PATH=/opt/models \
    PG_DATA_DIR=/data/pgdata

RUN mkdir -p /opt/models /data/pgdata && chown -R app:app /opt/models /data

WORKDIR /app
USER app

# Bake the embedding + reranker models into the image (~1.4 GB). After this the
# container needs no network for retrieval.
RUN python -c "from fastembed import TextEmbedding; from fastembed.rerank.cross_encoder import TextCrossEncoder; TextEmbedding(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'); TextCrossEncoder(model_name='jinaai/jina-reranker-v2-base-multilingual')"

COPY --chown=app:app app/ ./app/
COPY --chown=app:app scripts/ ./scripts/
COPY --chown=app:app .streamlit/ ./.streamlit/
COPY --chown=app:app streamlit_app.py ./
COPY --chown=app:app docker/entrypoint.sh docker/seed.py ./docker/
COPY --chown=app:app docker/seed.dump ./docker/seed.dump

# Defaults for a Groq deployment. Every one is overridable at run time; the
# compose file passes an --env-file for the secret and the tunables.
ENV LLM_PROVIDER=groq \
    LLM_MODEL=openai/gpt-oss-20b \
    GROQ_MODEL=openai/gpt-oss-20b \
    ROUTER_MODEL=groq::openai/gpt-oss-20b \
    EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
    EMBEDDING_DIM=384 \
    EMBEDDING_PREFIXES=0 \
    HYBRID=1 \
    RERANK=1 \
    RERANK_MODEL=jinaai/jina-reranker-v2-base-multilingual \
    RETRIEVE_CANDIDATES=30 \
    RERANK_TOP=8 \
    RRF_LEX_WEIGHT=0.7 \
    TS_CONFIG=simple \
    DATABASE_URL=embedded \
    STT=1 WHISPER_MODEL=medium WHISPER_LANG=fa \
    CORS_ORIGINS=* \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=6 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["streamlit", "run", "streamlit_app.py"]
