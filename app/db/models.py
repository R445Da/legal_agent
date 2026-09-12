"""
Minimal schema to start with. Two tables:

- documents: raw ingested legal text, one row per source document/case,
  kept regardless of how it's later chunked or used (this is the
  "archive" your colleague wants — reusable beyond just this RAG use case).
- chunks: retrieval units with embeddings, each pointing back to its
  parent document.

Swap pgvector's Vector(dim) size to match whatever embedding model you
pick (1536 for OpenAI text-embedding-3-small, 1024 for many local models, etc).

`EMBEDDING_DIM` must match `EMBEDDING_MODEL` in .env; the two are read in
different places and are not cross-checked. The wired default is
`intfloat/multilingual-e5-large` at 1024 dims (see app/rag/embeddings.py).
Changing either requires a schema rebuild + re-ingest, since the pgvector
column width is fixed and old vectors are not comparable.
"""

import os

from app.rag.textnorm import sql_translate_args
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "384"))

# Text-search config for the lexical half of hybrid retrieval. "simple" does no
# stemming (there is no Persian stemmer in stock Postgres) but it lowercases and
# tokenises, which is enough to make exact terms — names, case numbers, statute
# references — matchable, exactly where pure vector search is weakest.
TS_CONFIG = os.environ.get("TS_CONFIG", "simple")

# Entry text, folded exactly as `normalize_fa` folds a query, then indexed.
_FOLD_FROM, _FOLD_TO = sql_translate_args()
_ENTRY_TSVECTOR = (
    f"to_tsvector('{TS_CONFIG}', translate("
    "coalesce(title,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(raw_text,'')"
    f", '{_FOLD_FROM}', '{_FOLD_TO}'))"
)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String, nullable=False)       # where it came from
    title: Mapped[str] = mapped_column(String, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)   # court, date, jurisdiction, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    chunk_index: Mapped[int] = mapped_column(nullable=False)

    # Lexical index for hybrid (BM25-style) retrieval. Postgres keeps this in
    # sync with `text` automatically — it is a stored generated column.
    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{TS_CONFIG}', text)", persisted=True),
        nullable=True,
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_text_search", "text_search", postgresql_using="gin"),
    )


class Entry(Base):
    """
    Structured record the orchestrator extracts from a dictated/typed session.
    The raw text is also stored as a Document (chunked + embedded) so the same
    material is searchable by the RAG pipeline; this table is the "filled-in
    table" — parties, who represented whom, events, entities — that vector
    search alone can't answer relational questions against.
    """

    __tablename__ = "entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String, default="session")   # session | note | ...
    title: Mapped[str] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    parties: Mapped[list] = mapped_column(JSONB, default=list)        # [{"name","role"}]
    representation: Mapped[list] = mapped_column(JSONB, default=list) # [{"lawyer","client"}]
    events: Mapped[list] = mapped_column(JSONB, default=list)         # [{"date","description"}]
    entities: Mapped[dict] = mapped_column(JSONB, default=dict)       # {people,orgs,case_number,court,topic}
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    related_ids: Mapped[list] = mapped_column(JSONB, default=list)    # [document id] linked at creation
    # Richer than `related_ids`: the linked records with a match score and the
    # past outcome, so «پرونده‌های مشابه» can show why a link is there instead of
    # guessing from shared tags. [{entry_id, document_id, title, score, outcome}]
    related: Mapped[list] = mapped_column(JSONB, default=list)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Lexical index over everything an entry says, so questions are matched
    # with `ts_rank_cd` instead of a pile of ILIKEs and a home-made score.
    # The text is folded with the *same* character map `normalize_fa` uses (see
    # `textnorm.sql_translate_args`) — an Arabic yeh stored here has to match a
    # Persian yeh typed into the search box, and deriving both sides from one
    # table is what stops them drifting apart.
    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(_ENTRY_TSVECTOR, persisted=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_entries_text_search", "text_search", postgresql_using="gin"),
    )


class Label(Base):
    """Human judgments layered on top of the archive — the raw material for
    measuring and improving retrieval.

    kind = "relevance": after a search/ask, "was this retrieved chunk actually
      relevant to the query?"  -> query + chunk_id + value (1 good / 0 bad).
      Aggregated, these become a judged eval set (scripts/export_eval.py).
    kind = "tag": a category/label attached to a document, for filtering and
      to seed the taxonomy.
    kind = "review": a reviewer's verdict on an extracted Entry
      (confirmed / rejected / needs-fix).
    """

    __tablename__ = "labels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, nullable=False)          # relevance | tag | review
    target_type: Mapped[str] = mapped_column(String, nullable=False)   # chunk | document | entry
    target_id: Mapped[str] = mapped_column(String, nullable=False)     # uuid as text
    value: Mapped[str] = mapped_column(String, nullable=True)          # "1"/"0", a tag name, a verdict
    query: Mapped[str] = mapped_column(Text, nullable=True)            # for relevance labels
    note: Mapped[str] = mapped_column(Text, nullable=True)
    labeled_by: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_labels_kind_target", "kind", "target_type", "target_id"),
    )


class Meta(Base):
    """One-row-per-key store for facts about the data that outlive a process.

    Exists for exactly one reason today: an embedding model swap is the only
    misconfiguration in this system that produces *wrong answers* instead of an
    error. Vectors from two different models are not comparable, but they are
    the same shape, so nothing crashes — search just quietly returns nonsense.
    Recording which model wrote the vectors lets startup catch it.
    """

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Run(Base):
    """One pass of the entry-building pipeline (`app/rag/workflow.py`).

    A `Run` is the durable checkpoint: `state` is the whole `WorkflowState` as
    JSON, re-loadable after a browser reload or a backend failure so no step and
    no raw text is ever lost. Its `RunStep` rows are the log the build console
    (`/runs` on the API) reads back — one row per step attempt, with the model's
    output snapshot in `payload`.
    """

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, default="archive")   # archive | ...
    # running | awaiting_input | committed | failed | abandoned
    status: Mapped[str] = mapped_column(String, default="running")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)       # the full WorkflowState
    entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entries.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["RunStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunStep.seq"
    )

    __table_args__ = (Index("ix_runs_created", "created_at"),)


class RunStep(Base):
    """One step attempt inside a `Run` — the "meaningful logging" the user asked
    for. `payload` is the step's output (the extracted draft, the timeline rows,
    the similar list, the tool calls made), kept so the console can show what the
    model proposed against what the user changed."""

    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(nullable=False)              # order within the run
    step_id: Mapped[str] = mapped_column(String, nullable=False)  # classify | extract | ...
    label: Mapped[str] = mapped_column(String, nullable=True)     # Persian label
    # pending | running | done | failed | skipped | awaiting_input
    status: Mapped[str] = mapped_column(String, default="pending")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="steps")

    __table_args__ = (Index("ix_run_steps_run", "run_id", "seq"),)
