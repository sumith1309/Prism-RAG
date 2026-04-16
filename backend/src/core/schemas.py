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
    """Exec-only atomic visibility update. Either field is optional, but
    at least one must be provided.

    - ``disabled_for_roles``: roles to HIDE the doc from (guest/employee/
      manager). Executive is silently stripped — exec always keeps access.
    - ``doc_level``: reclassify the doc between 1 (PUBLIC) and 4
      (RESTRICTED). Changing level rewrites per-chunk metadata in Qdrant
      and the BM25 index so the vector-store RBAC filter picks up the new
      level without a full re-ingest.
    """
    disabled_for_roles: Optional[list[str]] = None
    doc_level: Optional[int] = None


class RetrievedChunk(BaseModel):
    text: str
    doc_id: str
    filename: str
    page: int
    section: str = ""
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    source_index: int = 0
    chunk_index: int = 0  # stable id within the doc — used by the graph viz


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
    # Agent-mode controls:
    # ``preferred_doc_id`` — hard-scope retrieval to a single document.
    #   Set by the frontend when the user clicks a candidate in the
    #   disambiguation card. Bypasses ambiguity detection on the retry.
    # ``override_intent`` — user-edited intent from the Intent Mirror pill.
    #   When set, we retrieve against this rewritten query instead of
    #   the raw input (original query is still shown in the chat bubble).
    # ``skip_disambiguation`` — emergency bypass if the user explicitly
    #   asks to search everything ("all docs", "don't ask, just answer").
    # ``compare_doc_ids`` — user clicked "Compare all" on a disambiguation
    #   card. Runs retrieval + generation ONCE per doc in parallel, emits
    #   a `comparison` event carrying one labelled answer per doc. Each
    #   doc's retrieval is scoped to just that doc, so there's no blending.
    preferred_doc_id: Optional[str] = None
    override_intent: Optional[str] = None
    skip_disambiguation: bool = False
    compare_doc_ids: list[str] = Field(default_factory=list)


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
    faithfulness: float = -1.0
    created_at: datetime
    # Agent: populated only when answer_mode == "disambiguate". Carries
    # the candidate docs offered to the user so thread-replay can re-
    # render the picker (greyed out once the user has chosen).
    disambiguation: Optional[dict] = None
    # Agent: populated only when answer_mode == "comparison". Carries
    # {columns: [per-doc answer objects]} so thread-replay can re-render
    # the side-by-side comparison view.
    comparison: Optional[dict] = None


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
