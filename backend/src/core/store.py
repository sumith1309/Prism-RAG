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


_engine = None


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
