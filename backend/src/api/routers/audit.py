"""Executive-only audit log endpoint."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.auth.dependencies import CurrentUser, require_level
from src.core import models

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditRow(BaseModel):
    id: int
    ts: datetime
    username: str
    user_level: int
    query: str
    refused: bool
    returned_chunks: int
    allowed_doc_ids: list[str]
    answer_mode: str = "grounded"
    latency_total_ms: int = 0
    latency_retrieve_ms: int = 0
    latency_rerank_ms: int = 0
    latency_generate_ms: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cached: bool = False
    corrective_retries: int = 0
    faithfulness: float = -1.0


class AuditResponse(BaseModel):
    total: int
    rows: list[AuditRow]


@router.get("", response_model=AuditResponse)
def list_audit(
    _user: CurrentUser = Depends(require_level(4)),
    limit: int = 500,
) -> AuditResponse:
    rows = models.list_audit(limit=limit)
    return AuditResponse(
        total=len(rows),
        rows=[
            AuditRow(
                id=int(r.id or 0),
                ts=r.ts,
                username=r.username,
                user_level=r.user_level,
                query=r.query,
                refused=bool(r.refused),
                returned_chunks=int(r.returned_chunks),
                allowed_doc_ids=[x for x in (r.allowed_doc_ids or "").split(",") if x],
                answer_mode=getattr(r, "answer_mode", None) or "grounded",
                latency_total_ms=int(getattr(r, "latency_total_ms", 0) or 0),
                latency_retrieve_ms=int(getattr(r, "latency_retrieve_ms", 0) or 0),
                latency_rerank_ms=int(getattr(r, "latency_rerank_ms", 0) or 0),
                latency_generate_ms=int(getattr(r, "latency_generate_ms", 0) or 0),
                tokens_prompt=int(getattr(r, "tokens_prompt", 0) or 0),
                tokens_completion=int(getattr(r, "tokens_completion", 0) or 0),
                cached=bool(getattr(r, "cached", False)),
                corrective_retries=int(getattr(r, "corrective_retries", 0) or 0),
                faithfulness=float(getattr(r, "faithfulness", -1.0) or -1.0),
            )
            for r in rows
        ],
    )
