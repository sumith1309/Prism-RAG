"""Public RAG playground — no auth, PUBLIC-only corpus, retrieval pipeline breakdown.

Returned payload includes dense top-k, BM25 top-k, RRF fused top-k, and
reranked top-k so the landing page can animate each stage. No LLM generation
is performed here — this is a visualization of the retrieval stack only.

Abuse mitigation:
  - IP-scoped sliding-window rate limit (20/min, 200/hour)
  - Only chunks with doc_level == 1 (PUBLIC) are ever searched
  - top_k clamped to [1, 5]
  - No LLM call, so token cost is zero
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque, Dict

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.pipelines.retrieval_pipeline import (
    _bm25_search,
    _dense_search,
    _rrf_fuse,
    _rerank,
    _tokenize,
)
from src.core import store

router = APIRouter(prefix="/api/playground", tags=["playground"])


# -------- rate limit -------------------------------------------------------
_minute_window = 60
_hour_window = 3600
_per_minute = 20
_per_hour = 200
_ip_buckets: Dict[str, Deque[float]] = {}
_lock = Lock()


def _rate_check(ip: str) -> None:
    now = time.time()
    with _lock:
        dq = _ip_buckets.setdefault(ip, deque())
        # keep only last hour
        while dq and now - dq[0] > _hour_window:
            dq.popleft()
        # minute check
        recent = sum(1 for t in dq if now - t <= _minute_window)
        if recent >= _per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Playground rate limit: max 20/min per IP. Try again in a moment.",
            )
        if len(dq) >= _per_hour:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Playground rate limit: max 200/hour per IP.",
            )
        dq.append(now)


# -------- DTOs -------------------------------------------------------------
class PlaygroundRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    top_k: int = Field(default=5, ge=1, le=5)


class PlaygroundHit(BaseModel):
    rank: int
    score: float
    doc_id: str
    filename: str
    page: int
    section: str = ""
    text: str


class PlaygroundStageResult(BaseModel):
    stage: str
    hits: list[PlaygroundHit]
    duration_ms: int


class PlaygroundResponse(BaseModel):
    query: str
    public_doc_count: int
    stages: list[PlaygroundStageResult]
    fused_top_filenames: list[str]  # the 5 docs a grounded answer would cite


# -------- endpoint ---------------------------------------------------------
@router.post("/retrieve", response_model=PlaygroundResponse)
async def playground_retrieve(req: PlaygroundRequest, request: Request):
    """Run the full retrieval stack on PUBLIC docs only; return per-stage results."""
    ip = (request.client.host if request.client else None) or "unknown"
    _rate_check(ip)

    public_docs = [d for d in store.list_documents() if int(d.doc_level or 1) <= 1]
    public_doc_ids = [d.doc_id for d in public_docs]
    if not public_doc_ids:
        raise HTTPException(
            status_code=503,
            detail="No PUBLIC documents are currently indexed.",
        )

    k = req.top_k

    # Stage 1 — dense search.
    t0 = time.perf_counter()
    dense = _dense_search(req.query, public_doc_ids, k=k, max_doc_level=1)
    dense_ms = int((time.perf_counter() - t0) * 1000)

    # Stage 2 — BM25 search.
    t1 = time.perf_counter()
    bm25 = _bm25_search(req.query, public_doc_ids, k=k, max_doc_level=1)
    bm25_ms = int((time.perf_counter() - t1) * 1000)

    # Stage 3 — RRF fusion.
    t2 = time.perf_counter()
    fused = _rrf_fuse(dense, bm25, k=60)[:k]
    rrf_ms = int((time.perf_counter() - t2) * 1000)

    # Stage 4 — cross-encoder rerank (only if we have candidates).
    t3 = time.perf_counter()
    reranked = _rerank(req.query, fused, top_n=k) if fused else []
    rerank_ms = int((time.perf_counter() - t3) * 1000)

    def _to_hits(tuples, score_idx: int = 2) -> list[PlaygroundHit]:
        out: list[PlaygroundHit] = []
        for i, t in enumerate(tuples, start=1):
            text = t[0]
            meta = t[1]
            score = float(t[score_idx]) if len(t) > score_idx else 0.0
            out.append(
                PlaygroundHit(
                    rank=i,
                    score=round(score, 4),
                    doc_id=str(meta.get("doc_id", "")),
                    filename=str(meta.get("filename", "")),
                    page=int(meta.get("page", 0) or 0),
                    section=str(meta.get("section", "")),
                    text=text[:400],
                )
            )
        return out

    def _rerank_hits(reranked_tuples) -> list[PlaygroundHit]:
        out: list[PlaygroundHit] = []
        for i, (text, meta, _rrf, rerank_score) in enumerate(reranked_tuples, start=1):
            out.append(
                PlaygroundHit(
                    rank=i,
                    score=round(float(rerank_score), 4),
                    doc_id=str(meta.get("doc_id", "")),
                    filename=str(meta.get("filename", "")),
                    page=int(meta.get("page", 0) or 0),
                    section=str(meta.get("section", "")),
                    text=text[:400],
                )
            )
        return out

    stages = [
        PlaygroundStageResult(
            stage="dense",
            hits=_to_hits(dense),
            duration_ms=dense_ms,
        ),
        PlaygroundStageResult(
            stage="bm25",
            hits=_to_hits(bm25),
            duration_ms=bm25_ms,
        ),
        PlaygroundStageResult(
            stage="rrf",
            hits=_to_hits(fused),
            duration_ms=rrf_ms,
        ),
        PlaygroundStageResult(
            stage="rerank",
            hits=_rerank_hits(reranked),
            duration_ms=rerank_ms,
        ),
    ]

    fused_filenames = [h.filename for h in stages[-1].hits] or [h.filename for h in stages[-2].hits]

    # Ensure query tokenization doesn't choke on odd chars.
    _tokenize(req.query)

    return PlaygroundResponse(
        query=req.query,
        public_doc_count=len(public_docs),
        stages=stages,
        fused_top_filenames=fused_filenames,
    )
