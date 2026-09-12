import os

from dotenv import load_dotenv

load_dotenv()


def _split(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


class Settings:
    llm_provider: str = os.environ.get("LLM_PROVIDER", "anthropic")
    llm_model: str | None = os.environ.get("LLM_MODEL")

    # Shared bearer token required on /ask, /search, /ingest, /documents.
    # Leave unset to run the API open (fine on localhost / a private tailnet,
    # not fine behind a public tunnel).
    api_token: str | None = os.environ.get("API_TOKEN") or None

    # Browser origins allowed to call the API. "*" (default) allows any origin,
    # which is safe only because every mutating route is token-gated.
    cors_origins: list[str] = _split(os.environ.get("CORS_ORIGINS", "*")) or ["*"]

    # DATABASE_URL=embedded (the default) boots a project-local PostgreSQL via
    # the `pgserver` package — no system Postgres, no Docker, no root needed.
    # Point it at a real postgresql+asyncpg:// URL to use an external database.
    database_url: str = os.environ.get("DATABASE_URL", "embedded")
    pg_data_dir: str = os.environ.get("PG_DATA_DIR", ".pgdata")

    # Local embedding model (fastembed / ONNX, runs offline after first download).
    embedding_model: str = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


settings = Settings()
