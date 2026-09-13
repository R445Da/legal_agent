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
from sqlalchemy import BigInteger, Computed, DateTime, ForeignKey, Index, String, Text, func
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
    # Legal references the entry cites: [{law, article, context, ref_id}]
    legal_refs: Mapped[list] = mapped_column(JSONB, default=list)
    # The aggregate this entry belongs to (legal_cases.case_number == entities.case_number)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legal_cases.id", ondelete="SET NULL"), nullable=True
    )
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


# =========================================================================== #
# Legal knowledge graph — two classifications, related.
#
#   1. Legal context   : LegalReference — the laws / articles / regulations /
#                        precedents a court refers to. Curated, versioned,
#                        rarely written by the model.
#   2. Case archive    : LegalCase — one row per case number, the aggregate an
#                        Entry (a session, a ruling, a note) belongs to.
#
# Persons and organizations are first-class rows so a lawyer, a company or a
# judge can be opened on its own and every case it touches listed. The typed
# junctions (`case_parties`, `case_references`) are the *relational* truth;
# `graph_edges` is the same information flattened into (src, relation, dst)
# triples so a neighbourhood walk of any node is one table scan and the graph
# can be exported to a real graph database (Neo4j / Cypher) unchanged.
# =========================================================================== #

_LAW_TSVECTOR = (
    f"to_tsvector('{TS_CONFIG}', translate("
    "coalesce(law_title,'') || ' ' || coalesce(article_no,'') || ' ' || "
    "coalesce(title,'') || ' ' || coalesce(text,'')"
    f", '{_FOLD_FROM}', '{_FOLD_TO}'))"
)
_CASE_TSVECTOR = (
    f"to_tsvector('{TS_CONFIG}', translate("
    "coalesce(case_number,'') || ' ' || coalesce(title,'') || ' ' || "
    "coalesce(case_type,'') || ' ' || coalesce(insurance_line,'') || ' ' || "
    "coalesce(court,'') || ' ' || coalesce(summary,'') || ' ' || coalesce(outcome,'')"
    f", '{_FOLD_FROM}', '{_FOLD_TO}'))"
)


class LegalReference(Base):
    """One citable unit of legal context: an article of a statute, a clause of
    a regulation (آیین‌نامه), or a precedent (رأی وحدت رویه)."""

    __tablename__ = "legal_refs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String, default="law")     # law | regulation | precedent | circular
    law_title: Mapped[str] = mapped_column(String, nullable=False)   # قانون بیمه
    law_year: Mapped[str | None] = mapped_column(String, nullable=True)   # ۱۳۱۶
    article_no: Mapped[str | None] = mapped_column(String, nullable=True)  # ۳۰
    title: Mapped[str | None] = mapped_column(String, nullable=True)      # short gloss
    text: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    ref_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # "قانون بیمه|30"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(_LAW_TSVECTOR, persisted=True), nullable=True
    )

    __table_args__ = (
        Index("ix_legal_refs_text_search", "text_search", postgresql_using="gin"),
        Index("ix_legal_refs_law", "law_title", "article_no"),
    )


class Person(Base):
    """A natural person seen in the archive: a party, a lawyer, a judge, an
    expert. `norm_name` is the honorific-stripped key two mentions merge on."""

    __tablename__ = "persons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    norm_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    roles: Mapped[list] = mapped_column(JSONB, default=list)     # distinct roles ever held
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    """A company, an insurer, a court, a fund, a public body."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    norm_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String, default="company")  # company | insurer | court | fund | agency | other
    roles: Mapped[list] = mapped_column(JSONB, default=list)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LegalCase(Base):
    """The case as a first-class record — what `cases.derive_cases()` used to
    recompute on every render. One row per case number; entries attach to it."""

    __tablename__ = "legal_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    case_type: Mapped[str | None] = mapped_column(String, nullable=True)       # e.g. جانشینی / بازیافت
    insurance_line: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. شخص ثالث
    court: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    group: Mapped[str | None] = mapped_column(String, nullable=True)           # حقوقی | کیفری | اداری | داوری
    status: Mapped[str] = mapped_column(String, default="open")               # open | closed | appeal | archived
    stage: Mapped[str | None] = mapped_column(String, nullable=True)           # بدوی | تجدیدنظر | اجرا | ...
    filed_date: Mapped[str | None] = mapped_column(String, nullable=True)      # Jalali, as text
    decided_date: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    claim_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ریال
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    text_search: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(_CASE_TSVECTOR, persisted=True), nullable=True
    )

    parties: Mapped[list["CaseParty"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    references: Mapped[list["CaseReference"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_legal_cases_text_search", "text_search", postgresql_using="gin"),
        Index("ix_legal_cases_type_line", "case_type", "insurance_line"),
    )


class CaseParty(Base):
    """Who is in a case and as what. Exactly one of person_id / org_id is set."""

    __tablename__ = "case_parties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_cases.id", ondelete="CASCADE"), nullable=False
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), nullable=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)   # khahan | khande | vakil_khahan | ...
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    case: Mapped["LegalCase"] = relationship(back_populates="parties")

    __table_args__ = (
        Index("ix_case_parties_case", "case_id"),
        Index("ix_case_parties_person", "person_id"),
        Index("ix_case_parties_org", "org_id"),
    )


class CaseReference(Base):
    """A case citing a unit of legal context, with how it was used."""

    __tablename__ = "case_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_cases.id", ondelete="CASCADE"), nullable=False
    )
    ref_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legal_refs.id", ondelete="CASCADE"), nullable=False
    )
    context: Mapped[str | None] = mapped_column(Text, nullable=True)   # «مبنای رد دفاع بیمه‌گر»
    used_by: Mapped[str | None] = mapped_column(String, nullable=True) # court | plaintiff | defendant | model
    weight: Mapped[float] = mapped_column(default=1.0)

    case: Mapped["LegalCase"] = relationship(back_populates="references")

    __table_args__ = (
        Index("ix_case_refs_case", "case_id"),
        Index("ix_case_refs_ref", "ref_id"),
    )


class GraphEdge(Base):
    """Flattened knowledge graph: (src) -[relation]-> (dst).

    node types: case | entry | document | person | org | law | label
    relations : HAS_ENTRY | HAS_DOCUMENT | PARTY (role in meta) | REPRESENTS |
                CITES | LABELED | SIMILAR_TO | HEARD_AT
    """

    __tablename__ = "graph_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    src_type: Mapped[str] = mapped_column(String, nullable=False)
    src_id: Mapped[str] = mapped_column(String, nullable=False)
    relation: Mapped[str] = mapped_column(String, nullable=False)
    dst_type: Mapped[str] = mapped_column(String, nullable=False)
    dst_id: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[float] = mapped_column(default=1.0)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_graph_src", "src_type", "src_id"),
        Index("ix_graph_dst", "dst_type", "dst_id"),
        Index("ix_graph_unique", "src_type", "src_id", "relation", "dst_type", "dst_id", unique=True),
    )


# =========================================================================== #
# v3 — answers with provenance
# =========================================================================== #
class Conversation(Base):
    """One chat thread, with the record it is currently working on.

    The chat used to live in `st.session_state["chat"]` — a list in one browser
    tab, so a reload lost it and neither the API nor any query could see it.
    As rows it survives, can be reopened, and can be deleted.

    `focus` is what makes a follow-up work without naming anything: whenever a
    turn touches a record — filed it, edited it, searched it — that record is
    stored here, so «نشانش بده» or «یک رویداد به تایم‌لاینش اضافه کن» resolves
    to the entry the user has been working on.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str | None] = mapped_column(String, nullable=True)   # first question, trimmed
    source: Mapped[str] = mapped_column(String, default="ui")          # ui | api | console
    # {"kind": "entry"|"case", "id": ..., "label": ...} — the current subject
    focus: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    __table_args__ = (Index("ix_conversations_updated", "updated_at"),)


class Message(Base):
    """One turn. `extra` carries whatever that turn rendered — provenance, the
    cases of a roster answer, a pending edit — so reopening a conversation
    shows what it showed, not a bare transcript."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)        # user | assistant
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conversation", "conversation_id", "created_at"),)


class AssistantAnswer(Base):
    """One answered question, with what it rested on (`app/rag/provenance.py`).

    `provenance` is the block the API and the chat show: numbered evidence,
    the tool trail, the citation check, token usage. Kept per answer so a
    demo can be replayed and a bad answer traced back to its evidence.
    """

    __tablename__ = "assistant_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String, default="api")      # api | ui | demo
    intent: Mapped[str] = mapped_column(String, nullable=False)     # law | cases | query | agent
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_assistant_answers_created", "created_at"),)


# =========================================================================== #
# v3 — webhooks (outbound, via an outbox) and CI events (inbound)
# =========================================================================== #
class WebhookSubscription(Base):
    """Where to send events and which ones. Each subscription signs its
    deliveries with its own secret (HMAC-SHA256, `X-Legal-Signature-256`)."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[list] = mapped_column(JSONB, default=list)    # ["run.step", "entry.committed", "*"]
    active: Mapped[bool] = mapped_column(default=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookDelivery(Base):
    """The outbox. Written in the same transaction as the event it reports,
    drained by whichever process gets there first (`FOR UPDATE SKIP LOCKED`).
    At-least-once: receivers dedupe on `X-Legal-Delivery` (this row's id)."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")   # pending | sent | failed | dead
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    response_code: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),)


class CiEvent(Base):
    """One CI event as received: a GitHub `workflow_run` / `workflow_job`
    webhook, a stage report from `scripts/ci_status.sh`, or a replayed fixture.
    `delivery_id` makes redelivery idempotent."""

    __tablename__ = "ci_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String, default="github")    # github | ci-step | replay
    event: Mapped[str] = mapped_column(String, nullable=False)       # workflow_run | workflow_job | ci_status | ping
    action: Mapped[str | None] = mapped_column(String, nullable=True)  # requested | in_progress | completed | queued
    repo: Mapped[str | None] = mapped_column(String, nullable=True)
    workflow_name: Mapped[str | None] = mapped_column(String, nullable=True)
    job_name: Mapped[str | None] = mapped_column(String, nullable=True)
    stage: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_number: Mapped[int | None] = mapped_column(nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    head_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)      # queued | in_progress | completed
    conclusion: Mapped[str | None] = mapped_column(String, nullable=True)  # success | failure | cancelled | …
    html_url: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_ci_events_run", "run_id", "received_at"),)
