import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import SQLModel, Field, create_engine, Session, select

from src.config import settings


class Document(SQLModel, table=True):
    doc_id: str = Field(primary_key=True)
    filename: str
    mime: str
    pages: int = 0
    chunks: int = 0
    sections: str = ""  # comma-separated
    doc_level: int = 1  # 1=PUBLIC, 2=INTERNAL, 3=CONFIDENTIAL, 4=RESTRICTED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Who uploaded this doc. Seeded corpus uses "system"/"system"; user
    # uploads populate these from the authenticated caller at ingest time.
    uploaded_by_username: str = ""
    uploaded_by_role: str = ""
    # Per-role visibility kill-switch the exec controls. Comma-separated list
    # of roles (guest/employee/manager) for which this doc is suppressed
    # in listings and retrieval — independent of the clearance filter. Exec
    # always sees every doc (they'd otherwise have no way to re-enable).
    disabled_for_roles: str = ""


class CorpusFact(SQLModel, table=True):
    """Policy/quantitative rule extracted from an uploaded document.

    Populated by `fact_extractor.extract_facts()` after a PDF/DOCX is
    ingested. The analytics agent retrieves these at query time to
    ground business-term filters in the ACTUAL corpus instead of a
    hardcoded block — so "30% retention cap" flows from Salary_Structure.pdf
    when sir uploads his TechNova dataset, and a totally different set of
    constants flows from a hospital or retail corpus.

    RBAC: inherits the parent doc's `doc_level` at retrieval time — we
    don't duplicate it here. A caller who can see the document can see
    every fact derived from it.
    """
    fact_id: str = Field(primary_key=True)
    doc_id: str = Field(index=True)           # FK to document.doc_id
    filename: str = ""
    section: str = ""                         # e.g. "§3", "Step 2", ""
    statement: str = ""                       # full sentence / paraphrase
    keywords: str = ""                        # comma-separated lower-case tokens
    quantity: Optional[float] = None          # numeric part if any
    unit: str = ""                            # "%", "INR_lakhs", "weeks", ...
    kind: str = ""                            # "threshold" | "cap" | "rate" | "policy"
    created_at: datetime = Field(default_factory=datetime.utcnow)


_engine = None


def _is_sqlite(engine) -> bool:
    """Detect engine dialect. Postgres and SQLite differ in how we
    add columns to existing tables, so `_migrate_columns` branches on
    this. Returns True for SQLite, False for Postgres (and anything
    else SQLAlchemy supports)."""
    try:
        return engine.dialect.name == "sqlite"
    except Exception:
        return True  # safe default for demo


def _migrate_columns(engine) -> None:
    """Lightweight forward-only migration. SQLite can't add columns via
    SQLModel.metadata.create_all on an existing table, so we manually
    ALTER TABLE for new fields. Safe to run repeatedly — skips columns
    that already exist. For Postgres production deployments, this is
    superseded by proper Alembic migrations (see
    ``backend/alembic/`` when added).
    """
    sqlite = _is_sqlite(engine)
    with engine.begin() as conn:
        from sqlalchemy import text

        # Helper — list existing columns for a table, dialect-aware.
        def existing_columns(table: str) -> set[str]:
            if sqlite:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                return {row[1] for row in rows}
            # Postgres — information_schema.
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :t"
                ),
                {"t": table.lower()},
            ).fetchall()
            return {row[0] for row in rows}

        # Document table — uploader identity + per-role visibility kill-switch.
        cols = existing_columns("document")
        for name, sqlite_ddl, pg_ddl in (
            (
                "uploaded_by_username",
                "TEXT NOT NULL DEFAULT ''",
                "TEXT NOT NULL DEFAULT ''",
            ),
            (
                "uploaded_by_role",
                "TEXT NOT NULL DEFAULT ''",
                "TEXT NOT NULL DEFAULT ''",
            ),
            (
                "disabled_for_roles",
                "TEXT NOT NULL DEFAULT ''",
                "TEXT NOT NULL DEFAULT ''",
            ),
        ):
            if name not in cols:
                ddl = sqlite_ddl if sqlite else pg_ddl
                conn.execute(text(f"ALTER TABLE document ADD COLUMN {name} {ddl}"))

        # ChatTurn table — per-turn faithfulness.
        cols = existing_columns("chatturn")
        for name, sqlite_ddl, pg_ddl in (
            (
                "faithfulness",
                "REAL NOT NULL DEFAULT -1.0",
                "DOUBLE PRECISION NOT NULL DEFAULT -1.0",
            ),
        ):
            if name not in cols:
                ddl = sqlite_ddl if sqlite else pg_ddl
                conn.execute(text(f"ALTER TABLE chatturn ADD COLUMN {name} {ddl}"))


def _get_engine():
    """Engine factory. Reads ``DATABASE_URL`` env var first — if set to a
    Postgres URL like ``postgresql://user:pass@host:5432/dbname``, uses
    Postgres. Otherwise falls back to the local SQLite file at
    ``settings.REGISTRY_DB``. The SQLite path is the zero-config demo
    default; Postgres is the production path.

    Tier 3.2 design note: we DON'T try to auto-migrate data from SQLite
    to Postgres — swapping engines requires running `seed.py --wipe`
    against the new DB. For real data migration, use `pg_dump` from
    SQLite (via `sqlite3 ... .dump | sed ... | psql ...`) or a dedicated
    ETL tool.
    """
    global _engine
    if _engine is not None:
        return _engine

    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Postgres (or any SQLAlchemy-supported URL)
        if url.startswith("postgres://"):
            # Heroku/Railway historically emit postgres://; SQLAlchemy
            # wants postgresql://. Normalize so copy-paste URLs work.
            url = "postgresql://" + url[len("postgres://"):]
        _engine = create_engine(url, echo=False, pool_pre_ping=True)
    else:
        db_path = settings.abs(settings.REGISTRY_DB)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)

    # Register User + AuditLog tables (declared in models.py) before create_all
    # so the seed script can write to them on first run.
    from src.core import models  # noqa: F401
    SQLModel.metadata.create_all(_engine)
    _migrate_columns(_engine)
    return _engine


def add_document(doc: Document) -> None:
    with Session(_get_engine()) as session:
        session.merge(doc)
        session.commit()


def list_documents() -> list[Document]:
    with Session(_get_engine()) as session:
        return list(session.exec(select(Document).order_by(Document.created_at.desc())))


def get_document(doc_id: str) -> Optional[Document]:
    with Session(_get_engine()) as session:
        return session.get(Document, doc_id)


def delete_document(doc_id: str) -> bool:
    with Session(_get_engine()) as session:
        d = session.get(Document, doc_id)
        if not d:
            return False
        session.delete(d)
        session.commit()
        return True


def get_document_by_filename(filename: str) -> Optional[Document]:
    with Session(_get_engine()) as session:
        return session.exec(select(Document).where(Document.filename == filename)).first()


def set_disabled_roles(doc_id: str, roles: list[str]) -> Optional[Document]:
    """Exec-only toggle. Overwrites the per-role visibility kill-switch."""
    clean = ",".join(sorted({r.strip() for r in roles if r and r.strip()}))
    with Session(_get_engine()) as session:
        d = session.get(Document, doc_id)
        if not d:
            return None
        d.disabled_for_roles = clean
        session.add(d)
        session.commit()
        session.refresh(d)
        return d


def doc_is_visible_to(doc: Document, role: str, level: int) -> bool:
    """Combined gate: clearance + exec's per-role kill-switch. Exec (L4)
    always passes — they need visibility to manage disabled docs."""
    if int(doc.doc_level or 1) > int(level or 0):
        return False
    if (role or "") == "executive":
        return True
    disabled = {r for r in (doc.disabled_for_roles or "").split(",") if r}
    return role not in disabled


# ── Corpus facts (extracted policy rules) ────────────────────────────────

def add_corpus_facts(facts: list[CorpusFact]) -> None:
    """Bulk-insert extracted facts. Uses merge so re-extraction overwrites."""
    if not facts:
        return
    with Session(_get_engine()) as session:
        for f in facts:
            session.merge(f)
        session.commit()


def list_corpus_facts(
    doc_ids: Optional[list[str]] = None,
    max_doc_level: Optional[int] = None,
) -> list[CorpusFact]:
    """Return facts scoped to the caller's visible docs.

    `doc_ids` — if provided, restrict to these documents only.
    `max_doc_level` — RBAC ceiling; caller's clearance level.
    """
    with Session(_get_engine()) as session:
        stmt = select(CorpusFact)
        if doc_ids:
            stmt = stmt.where(CorpusFact.doc_id.in_(doc_ids))
        facts = list(session.exec(stmt))
        if max_doc_level is None:
            return facts
        # Filter by parent doc_level — batch-lookup to avoid N queries
        doc_rows = session.exec(
            select(Document.doc_id, Document.doc_level)
        ).all()
        level_map = {d.doc_id: d.doc_level for d in doc_rows}
        return [f for f in facts if level_map.get(f.doc_id, 1) <= max_doc_level]


def delete_corpus_facts_for_doc(doc_id: str) -> int:
    """Remove all facts derived from a document (e.g. before re-extraction)."""
    with Session(_get_engine()) as session:
        rows = list(
            session.exec(select(CorpusFact).where(CorpusFact.doc_id == doc_id))
        )
        for r in rows:
            session.delete(r)
        session.commit()
        return len(rows)
