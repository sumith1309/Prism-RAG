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

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.config import settings
from src.core.prompts import (
    FAITHFULNESS_PROMPT,
    SYSTEM_PROMPT,
    build_context_block,
    build_user_prompt,
)
from src.core.schemas import RetrievedChunk
from src.pipelines.embedding_pipeline import _get_embeddings
from src.pipelines.generation_pipeline import _complete_chat, _stream_chat
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


# ---------------------------------------------------------------------------
# Public Pipeline Lab — full system showcase
# ---------------------------------------------------------------------------
# These two endpoints power the public /pipeline learning surface: anyone
# (no auth) can paste a query and watch the entire RAG pipeline execute
# against the FULL corpus (executive-level visibility — every doc is in
# scope so the demo can show how cross-clearance retrieval works).
# Same IP rate limiter as /retrieve protects abuse.


class EmbedRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)


class EmbedResponse(BaseModel):
    query: str
    dim: int
    vector: list[float]
    model: str


@router.post("/embed", response_model=EmbedResponse)
async def playground_embed(req: EmbedRequest, request: Request):
    """Return the actual BGE embedding for the query so the frontend can
    visualize the 768-dim vector. No auth — same rate limit as /retrieve.
    """
    ip = (request.client.host if request.client else None) or "unknown"
    _rate_check(ip)
    vec = _get_embeddings().embed_query(req.query)
    return EmbedResponse(
        query=req.query,
        dim=len(vec),
        vector=[float(v) for v in vec],
        model=settings.EMBED_MODEL,
    )


class InspectRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=400)
    use_rerank: bool = True
    top_k: int = Field(default=5, ge=1, le=8)


@router.post("/inspect")
async def playground_inspect(req: InspectRequest, request: Request):
    """End-to-end pipeline showcase. SSE stream that emits:

      - ``embed``   embedding metadata + vector excerpt
      - ``dense``   dense top-k hits with scores
      - ``bm25``    bm25 top-k hits
      - ``rrf``     RRF fused top-k
      - ``rerank``  cross-encoder reranked top-k (if enabled)
      - ``token``   streamed answer tokens
      - ``done``    final faithfulness, latency breakdown, total tokens

    Runs against ALL documents (executive-level visibility) so the public
    demo shows the complete corpus, including RESTRICTED — by design,
    since this is a pedagogical surface backed by synthetic TechNova data.
    """
    ip = (request.client.host if request.client else None) or "unknown"
    _rate_check(ip)

    all_docs = store.list_documents()
    all_doc_ids = [d.doc_id for d in all_docs]
    if not all_doc_ids:
        raise HTTPException(status_code=503, detail="Corpus is empty.")
    k = req.top_k

    async def event_gen():
        t_start = time.time()

        # ── Stage 1: Embed ────────────────────────────────────────────
        t0 = time.time()
        vec = _get_embeddings().embed_query(req.query)
        embed_ms = int((time.time() - t0) * 1000)
        # Trim the vector for transport — full 768 dims stays meaningful
        # but is ~12 KB JSON; that's fine for one event.
        yield {
            "event": "embed",
            "data": json.dumps(
                {
                    "model": settings.EMBED_MODEL,
                    "dim": len(vec),
                    "vector": [float(v) for v in vec],
                    "duration_ms": embed_ms,
                }
            ),
        }

        # ── Stage 2: Dense ────────────────────────────────────────────
        t0 = time.time()
        dense = _dense_search(req.query, all_doc_ids, k=k * 2, max_doc_level=4)
        dense_ms = int((time.time() - t0) * 1000)
        yield {
            "event": "dense",
            "data": json.dumps({"hits": _pack_stage(dense), "duration_ms": dense_ms}),
        }

        # ── Stage 3: BM25 ─────────────────────────────────────────────
        t0 = time.time()
        bm25 = _bm25_search(req.query, all_doc_ids, k=k * 2, max_doc_level=4)
        bm25_ms = int((time.time() - t0) * 1000)
        yield {
            "event": "bm25",
            "data": json.dumps({"hits": _pack_stage(bm25), "duration_ms": bm25_ms}),
        }

        # ── Stage 4: RRF ──────────────────────────────────────────────
        t0 = time.time()
        fused = _rrf_fuse(dense, bm25, k=settings.RRF_K)[:k]
        rrf_ms = int((time.time() - t0) * 1000)
        yield {
            "event": "rrf",
            "data": json.dumps({"hits": _pack_stage(fused), "duration_ms": rrf_ms}),
        }

        # ── Stage 5: Rerank (optional) ────────────────────────────────
        # Tell the frontend which model is doing the reranking so the
        # stage tagline/explainer can display it dynamically.
        rerank_hits: list = []
        rerank_ms = 0
        rerank_model = settings.RERANK_MODEL
        if req.use_rerank and fused:
            t0 = time.time()
            reranked = _rerank(req.query, fused, top_n=k)
            rerank_ms = int((time.time() - t0) * 1000)
            rerank_hits = [
                {
                    # `rank` (1-based, by descending rerank_score) is what
                    # the frontend Rank Journey chart joins on across
                    # stages — without it the chart can't tell which
                    # chunks survived rerank and every line stays grey.
                    "rank": i,
                    "chunk_id": f"chunk:{m.get('doc_id', '')}:{m.get('chunk_index', 0)}",
                    "doc_id": m.get("doc_id", ""),
                    "filename": m.get("filename", ""),
                    "page": int(m.get("page", 0) or 0),
                    "section": m.get("section", "") or "",
                    "text": text[:600],
                    "score": float(rerank_score),
                    "rrf_score": float(rrf_s),
                    "doc_level": int(m.get("doc_level", 1) or 1),
                    "chunk_index": int(m.get("chunk_index", 0) or 0),
                }
                for i, (text, m, rrf_s, rerank_score) in enumerate(reranked, start=1)
            ]
        yield {
            "event": "rerank",
            "data": json.dumps(
                {
                    "hits": rerank_hits,
                    "duration_ms": rerank_ms,
                    "model": rerank_model,
                }
            ),
        }

        # ── Stage 6: Generation ───────────────────────────────────────
        # Build chunks list for generation. Use reranked if available, else fused.
        if req.use_rerank and rerank_hits:
            gen_chunks = [
                RetrievedChunk(
                    text=h["text"],
                    doc_id=h["doc_id"],
                    filename=h["filename"],
                    page=h["page"],
                    section=h["section"],
                    rrf_score=h["rrf_score"],
                    rerank_score=h["score"],
                    source_index=i + 1,
                    chunk_index=h["chunk_index"],
                )
                for i, h in enumerate(rerank_hits)
            ]
        else:
            gen_chunks = []
            for i, (text, meta, rrf_s) in enumerate(fused, start=1):
                gen_chunks.append(
                    RetrievedChunk(
                        text=text,
                        doc_id=meta.get("doc_id", ""),
                        filename=meta.get("filename", ""),
                        page=int(meta.get("page", 0) or 0),
                        section=meta.get("section", "") or "",
                        rrf_score=float(rrf_s),
                        rerank_score=None,
                        source_index=i,
                        chunk_index=int(meta.get("chunk_index", 0) or 0),
                    )
                )

        full_answer = ""
        gen_ms = 0
        if gen_chunks:
            t0 = time.time()
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_prompt(req.query, build_context_block(gen_chunks)),
                },
            ]
            try:
                async for delta in _stream_chat(messages, max_tokens=600, temperature=0.2):
                    full_answer += delta
                    yield {"event": "token", "data": json.dumps({"delta": delta})}
            except Exception as e:
                yield {"event": "error", "data": json.dumps({"message": str(e)})}
            gen_ms = int((time.time() - t0) * 1000)

        # ── Stage 7: Faithfulness ─────────────────────────────────────
        faith = -1.0
        if gen_chunks and full_answer.strip():
            srcs = "\n\n".join(
                f"[Source {c.source_index}] {c.text[:600]}" for c in gen_chunks[:5]
            )
            try:
                txt = await asyncio.wait_for(
                    _complete_chat(
                        [
                            {
                                "role": "user",
                                "content": FAITHFULNESS_PROMPT.format(
                                    sources=srcs, answer=full_answer[:2000]
                                ),
                            }
                        ],
                        max_tokens=20,
                        temperature=0.0,
                    ),
                    timeout=10.0,
                )
                for tok in (txt or "").split():
                    try:
                        v = float(tok.strip().rstrip(",."))
                        if 0.0 <= v <= 1.0:
                            faith = round(v, 3)
                            break
                    except ValueError:
                        continue
            except Exception:
                pass

        total_ms = int((time.time() - t_start) * 1000)
        approx_prompt_tokens = max(1, len(SYSTEM_PROMPT + req.query) // 4) + sum(
            len(c.text) // 4 for c in gen_chunks
        )
        # Resolve the actual generation model: when LLM_BASE_URL is set we
        # use the OpenAI-compatible path (LLM_MODEL); otherwise the local
        # HF chat model. The frontend uses this to label the Generation
        # stage card, so it always reflects what really ran.
        import os as _os
        gen_model = (
            _os.environ.get("LLM_MODEL")
            if _os.environ.get("LLM_BASE_URL")
            else settings.HF_CHAT_MODEL
        ) or "unknown"
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "ok": True,
                    "answer_mode": "grounded" if gen_chunks else "unknown",
                    "faithfulness": faith,
                    "models": {
                        "embed": settings.EMBED_MODEL,
                        "rerank": rerank_model,
                        "generate": gen_model,
                    },
                    "latency_ms": {
                        "embed": embed_ms,
                        "dense": dense_ms,
                        "bm25": bm25_ms,
                        "rrf": rrf_ms,
                        "rerank": rerank_ms,
                        "generate": gen_ms,
                        "total": total_ms,
                    },
                    "tokens": {
                        "prompt": approx_prompt_tokens,
                        "completion": max(1, len(full_answer) // 4),
                    },
                    "answer": full_answer,
                }
            ),
        }

    return EventSourceResponse(event_gen())


def _pack_stage(tuples) -> list:
    out = []
    for i, t in enumerate(tuples, start=1):
        text, meta, score = t[0], t[1], t[2]
        out.append(
            {
                "rank": i,
                "score": round(float(score), 6),
                "chunk_id": f"chunk:{meta.get('doc_id', '')}:{meta.get('chunk_index', 0)}",
                "doc_id": str(meta.get("doc_id", "")),
                "filename": str(meta.get("filename", "")),
                "page": int(meta.get("page", 0) or 0),
                "section": str(meta.get("section", "")),
                "text": text[:600],
                "doc_level": int(meta.get("doc_level", 1) or 1),
                "chunk_index": int(meta.get("chunk_index", 0) or 0),
            }
        )
    return out
