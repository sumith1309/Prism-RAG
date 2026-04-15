from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    mime: str
    pages: int
    chunks: int
    sections: list[str] = Field(default_factory=list)
    doc_level: int = 1
    classification: str = "PUBLIC"
    created_at: datetime
    uploaded_by_username: str = ""
    uploaded_by_role: str = ""
    disabled_for_roles: list[str] = Field(default_factory=list)


class VisibilityUpdate(BaseModel):
    """Exec-only: roles to HIDE the document from (guest/employee/manager).
    Executive is never in this list — the exec always retains visibility."""
    disabled_for_roles: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    text: str
    doc_id: str
    filename: str
    page: int
    section: str = ""
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    source_index: int = 0


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    query: str
    doc_ids: list[str] = Field(default_factory=list)
    use_hyde: bool = False
    use_rerank: bool = True
    use_multi_query: bool = False  # fan out query into 3 LLM variants (slower, higher recall)
    use_corrective: bool = True  # auto-retry with LLM rewrite on weak first pass
    use_faithfulness: bool = True  # LLM-judge answer vs sources (adds 1-3s)
    section_filter: Optional[list[str]] = None
    history: list[ChatMessage] = Field(default_factory=list)
    top_k: int = 5
    thread_id: Optional[str] = None  # None = create new thread on first turn


class ThreadSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ThreadTurn(BaseModel):
    id: int
    role: str
    content: str
    sources: list[dict] = Field(default_factory=list)
    refused: bool = False
    answer_mode: str = "grounded"
    created_at: datetime


class ThreadDetail(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turns: list[ThreadTurn]


class RenameRequest(BaseModel):
    title: str


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    status: str
    chunks: int = 0
    pages: int = 0
    error: Optional[str] = None
