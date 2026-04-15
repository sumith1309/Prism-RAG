"""SQLModel tables for auth, audit, and chat threads.

Kept in a single module because they share the same engine as the Document
registry in ``store.py`` — ``store._get_engine()`` creates tables for every
SQLModel subclass declared at import time.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, delete, select

from src.core.store import _get_engine


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: str  # guest | employee | manager | executive
    level: int  # 1..4, mirrors role for fast filter math
    title: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    user_id: int = Field(index=True)
    username: str
    user_level: int
    query: str
    refused: bool = False
    returned_chunks: int = 0
    allowed_doc_ids: str = ""  # comma-separated doc_ids actually cited
    answer_mode: str = "grounded"  # grounded | refused | general | unknown
    # Observability columns
    latency_retrieve_ms: int = 0
    latency_rerank_ms: int = 0
    latency_generate_ms: int = 0
    latency_total_ms: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cached: bool = False
    corrective_retries: int = 0
    faithfulness: float = -1.0  # -1 = not measured


class ChatThread(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: int = Field(index=True)
    title: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ChatTurn(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: str = Field(index=True)
    role: str  # "user" | "assistant"
    content: str
    sources_json: str = ""  # JSON-serialized list[Source]
    refused: bool = False
    answer_mode: str = "grounded"  # grounded | refused | general | unknown | social | meta
    # LLM-judge faithfulness for assistant turns. -1 means "not scored"
    # (faithfulness disabled, non-grounded mode, or scoring timed out).
    # Persisted on the turn so the graph viz's Faithfulness Rings + replay
    # can colour each cited chunk without joining against the audit log.
    faithfulness: float = -1.0
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


# --- CRUD helpers -----------------------------------------------------------


def get_user_by_username(username: str) -> Optional[User]:
    with Session(_get_engine()) as s:
        return s.exec(select(User).where(User.username == username)).first()


def upsert_user(user: User) -> User:
    with Session(_get_engine()) as s:
        existing = s.exec(select(User).where(User.username == user.username)).first()
        if existing:
            existing.password_hash = user.password_hash
            existing.role = user.role
            existing.level = user.level
            existing.title = user.title
            s.add(existing)
            s.commit()
            s.refresh(existing)
            return existing
        s.add(user)
        s.commit()
        s.refresh(user)
        return user


def list_users() -> list[User]:
    with Session(_get_engine()) as s:
        return list(s.exec(select(User).order_by(User.level)))


def write_audit(entry: AuditLog) -> None:
    with Session(_get_engine()) as s:
        s.add(entry)
        s.commit()


def list_audit(limit: int = 500) -> list[AuditLog]:
    with Session(_get_engine()) as s:
        return list(s.exec(select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit)))


# --- chat threads ---------------------------------------------------------


def new_thread_id() -> str:
    return uuid.uuid4().hex[:12]


def create_thread(user_id: int, title: str = "") -> ChatThread:
    thread = ChatThread(id=new_thread_id(), user_id=int(user_id), title=title)
    with Session(_get_engine()) as s:
        s.add(thread)
        s.commit()
        s.refresh(thread)
    return thread


def get_thread(thread_id: str, user_id: int) -> Optional[ChatThread]:
    """Returns the thread only if it belongs to ``user_id`` — else None (404 at router)."""
    with Session(_get_engine()) as s:
        t = s.get(ChatThread, thread_id)
        if t is None or int(t.user_id) != int(user_id):
            return None
        return t


def list_threads(user_id: int, limit: int = 200) -> list[ChatThread]:
    with Session(_get_engine()) as s:
        return list(
            s.exec(
                select(ChatThread)
                .where(ChatThread.user_id == int(user_id))
                .order_by(ChatThread.updated_at.desc())
                .limit(limit)
            )
        )


def rename_thread(thread_id: str, user_id: int, title: str) -> Optional[ChatThread]:
    with Session(_get_engine()) as s:
        t = s.get(ChatThread, thread_id)
        if t is None or int(t.user_id) != int(user_id):
            return None
        t.title = title
        t.updated_at = datetime.utcnow()
        s.add(t)
        s.commit()
        s.refresh(t)
        return t


def touch_thread(thread_id: str) -> None:
    """Bump updated_at without changing other fields. Unsafe to call without prior auth check."""
    with Session(_get_engine()) as s:
        t = s.get(ChatThread, thread_id)
        if t is None:
            return
        t.updated_at = datetime.utcnow()
        s.add(t)
        s.commit()


def delete_thread(thread_id: str, user_id: int) -> bool:
    with Session(_get_engine()) as s:
        t = s.get(ChatThread, thread_id)
        if t is None or int(t.user_id) != int(user_id):
            return False
        s.exec(delete(ChatTurn).where(ChatTurn.thread_id == thread_id))
        s.delete(t)
        s.commit()
        return True


def append_turn(
    thread_id: str,
    role: str,
    content: str,
    sources_json: str = "",
    refused: bool = False,
    answer_mode: str = "grounded",
    faithfulness: float = -1.0,
) -> ChatTurn:
    turn = ChatTurn(
        thread_id=thread_id,
        role=role,
        content=content,
        sources_json=sources_json,
        refused=refused,
        answer_mode=answer_mode,
        faithfulness=faithfulness,
    )
    with Session(_get_engine()) as s:
        s.add(turn)
        s.commit()
        s.refresh(turn)
    return turn


def list_turns(thread_id: str) -> list[ChatTurn]:
    with Session(_get_engine()) as s:
        return list(
            s.exec(
                select(ChatTurn)
                .where(ChatTurn.thread_id == thread_id)
                .order_by(ChatTurn.created_at.asc())
            )
        )
