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


_engine = None


def _migrate_columns(engine) -> None:
    """SQLite can't add columns via SQLModel.metadata.create_all on an
    existing table, so we manually ALTER TABLE for new fields. Safe to
    run repeatedly — skips columns that already exist."""
    with engine.begin() as conn:
        from sqlalchemy import text

        # Document table — uploader identity + per-role visibility kill-switch.
        cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(document)")).fetchall()
        }
        for name, ddl in (
            ("uploaded_by_username", "TEXT NOT NULL DEFAULT ''"),
            ("uploaded_by_role", "TEXT NOT NULL DEFAULT ''"),
            ("disabled_for_roles", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE document ADD COLUMN {name} {ddl}"))

        # ChatTurn table — per-turn faithfulness for graph replay + rings.
        cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(chatturn)")).fetchall()
        }
        for name, ddl in (
            ("faithfulness", "REAL NOT NULL DEFAULT -1.0"),
        ):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE chatturn ADD COLUMN {name} {ddl}"))


def _get_engine():
    global _engine
    if _engine is None:
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
