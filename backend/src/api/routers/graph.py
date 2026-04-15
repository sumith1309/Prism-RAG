"""Knowledge-graph endpoints powering the 3D visualization.

Three endpoints, three layers of truth:

- GET  /api/graph         — corpus structure (docs + chunks + containment)
- GET  /api/graph/heat    — observability heat (retrieved/cited counts)
- POST /api/graph/trace   — live query overlay (which nodes the pipeline
                             touched, stage by stage)

All endpoints respect clearance: a caller only sees docs their role has
access to. The RBAC Lens on the frontend is purely a *visualization* —
the exec (who has full clearance) can flip the Lens to "as Manager" and
watch restricted nodes fade, but the server never returns docs above
the caller's own level.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from qdrant_client.http import models as qm
from sqlmodel import Session, select

from src.auth.dependencies import CurrentUser, get_current_user
from src.config import settings
from src.core import models, store
from src.core.store import _get_engine, doc_is_visible_to
from src.pipelines.embedding_pipeline import get_qdrant
from src.pipelines.retrieval_pipeline import _bm25_search, _dense_search, _rerank, _rrf_fuse

router = APIRouter(prefix="/api/graph", tags=["graph"])


class GraphNode(BaseModel):
    id: str
    type: str  # "doc" | "chunk"
    label: str
    doc_id: Optional[str] = None
    classification: Optional[str] = None
    doc_level: Optional[int] = None
    disabled_for_roles: list[str] = Field(default_factory=list)
    uploaded_by_username: Optional[str] = None
    uploaded_by_role: Optional[str] = None
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_index: Optional[int] = None
    text_preview: Optional[str] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: str  # "contains"


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    stats: dict


_LEVEL_LABELS = {1: "PUBLIC", 2: "INTERNAL", 3: "CONFIDENTIAL", 4: "RESTRICTED"}


def _scroll_all_chunks(doc_ids: set[str]) -> list[dict]:
    """Scroll Qdrant for every chunk belonging to the given doc_ids."""
    client = get_qdrant()
    out: list[dict] = []
    offset = None
    while True:
        batch, offset = client.scroll(
            settings.QDRANT_COLLECTION,
            scroll_filter=qm.Filter(
                must=[qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=list(doc_ids)))]
            )
            if doc_ids
            else None,
            limit=256,
            with_payload=True,
            offset=offset,
        )
        for p in batch:
            pl = p.payload or {}
            if not pl.get("doc_id"):
                continue
            out.append(pl)
        if not offset:
            break
    return out


@router.get("", response_model=GraphResponse)
async def get_graph(user: CurrentUser = Depends(get_current_user)):
    """Return the corpus graph filtered to what the caller is allowed to
    see. Executive sees everything; lower roles see only their accessible
    docs. The frontend's RBAC Lens dims further but cannot expose more.
    """
    visible_docs = [
        d for d in store.list_documents() if doc_is_visible_to(d, user.role, user.level)
    ]
    visible_ids = {d.doc_id for d in visible_docs}

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for d in visible_docs:
        lvl = int(d.doc_level or 1)
        nodes.append(
            GraphNode(
                id=f"doc:{d.doc_id}",
                type="doc",
                label=d.filename,
                doc_id=d.doc_id,
                classification=_LEVEL_LABELS.get(lvl, "PUBLIC"),
                doc_level=lvl,
                disabled_for_roles=[r for r in (d.disabled_for_roles or "").split(",") if r],
                uploaded_by_username=d.uploaded_by_username or "",
                uploaded_by_role=d.uploaded_by_role or "",
            )
        )

    chunks = _scroll_all_chunks(visible_ids)
    for c in chunks:
        doc_id = c["doc_id"]
        idx = int(c.get("chunk_index", 0) or 0)
        cid = f"chunk:{doc_id}:{idx}"
        nodes.append(
            GraphNode(
                id=cid,
                type="chunk",
                label=f"p.{c.get('page', 0)} · {c.get('section', '') or 'chunk'}",
                doc_id=doc_id,
                classification=_LEVEL_LABELS.get(int(c.get("doc_level", 1) or 1), "PUBLIC"),
                doc_level=int(c.get("doc_level", 1) or 1),
                page=int(c.get("page", 0) or 0),
                section=c.get("section", "") or "",
                chunk_index=idx,
                text_preview=(c.get("text") or "")[:240],
            )
        )
        edges.append(GraphEdge(source=f"doc:{doc_id}", target=cid, kind="contains"))

    stats = {
        "docs": len(visible_docs),
        "chunks": len(chunks),
        "by_classification": {
            lbl: sum(1 for d in visible_docs if _LEVEL_LABELS.get(int(d.doc_level or 1)) == lbl)
            for lbl in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED")
        },
    }

    return GraphResponse(nodes=nodes, edges=edges, stats=stats)


class HeatResponse(BaseModel):
    docs: dict
    chunks: dict
    total_queries: int
    total_citations: int


@router.get("/heat", response_model=HeatResponse)
async def get_heat(user: CurrentUser = Depends(get_current_user)):
    """Per-doc retrieval count (from AuditLog.allowed_doc_ids) and
    per-chunk citation count (from ChatTurn.sources_json). Scoped to
    audit rows for docs the caller can see — so heat is coherent with
    the structure endpoint's visibility."""
    visible_docs = [
        d for d in store.list_documents() if doc_is_visible_to(d, user.role, user.level)
    ]
    visible_doc_ids = {d.doc_id for d in visible_docs}

    doc_retrieved = Counter()
    chunk_cited: dict[str, int] = defaultdict(int)
    total_queries = 0
    total_citations = 0

    with Session(_get_engine()) as s:
        for row in s.exec(select(models.AuditLog)):
            if not row.allowed_doc_ids:
                continue
            hit_ids = [x for x in row.allowed_doc_ids.split(",") if x in visible_doc_ids]
            if not hit_ids:
                continue
            total_queries += 1
            for did in set(hit_ids):
                doc_retrieved[did] += 1

        # Chunk-level citation heat from ChatTurn.sources_json
        for row in s.exec(
            select(models.ChatTurn).where(models.ChatTurn.role == "assistant")
        ):
            if not row.sources_json:
                continue
            try:
                sources = json.loads(row.sources_json)
            except Exception:
                continue
            for src in sources:
                did = src.get("doc_id")
                idx = src.get("chunk_index")
                # `chunk_index` isn't in the Source schema we emit; fall back
                # on a best-effort key using (doc_id, page) so heat at least
                # lights up the parent doc even when chunk granularity is lost.
                if did and did in visible_doc_ids:
                    key = f"chunk:{did}:{idx}" if idx is not None else f"doc:{did}"
                    chunk_cited[key] += 1
                    total_citations += 1

    return HeatResponse(
        docs={did: {"retrieved": c} for did, c in doc_retrieved.items()},
        chunks={cid: {"cited": c} for cid, c in chunk_cited.items()},
        total_queries=total_queries,
        total_citations=total_citations,
    )


class TraceRequest(BaseModel):
    query: str
    role_override: Optional[str] = None  # "guest" | "employee" | "manager" — for Lens simulation
    top_k: int = 5


class TraceStageHit(BaseModel):
    chunk_id: str
    doc_id: str
    score: float


class TraceResponse(BaseModel):
    query: str
    role: str
    level: int
    dense: list[TraceStageHit]
    bm25: list[TraceStageHit]
    rrf: list[TraceStageHit]
    rerank: list[TraceStageHit]
    latency_ms: int


_ROLE_LEVEL = {"guest": 1, "employee": 2, "manager": 3, "executive": 4}


@router.post("/trace", response_model=TraceResponse)
async def trace_query(req: TraceRequest, user: CurrentUser = Depends(get_current_user)):
    """Run each stage of the retrieval pipeline on the query and return
    which chunks lit up at each step. The frontend uses this to animate
    the graph as the user types.

    ``role_override`` (exec-only) re-evaluates retrieval as if the caller
    were that lower role — used by the RBAC Lens to simulate what a
    Guest/Employee/Manager would see for the same query. Non-exec
    callers always get their own role's view.
    """
    q = (req.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query must not be empty")

    # Determine effective role + level.
    if req.role_override and user.role == "executive":
        override = req.role_override.lower()
        if override not in _ROLE_LEVEL:
            raise HTTPException(status_code=400, detail=f"unknown role {override!r}")
        eff_role = override
        eff_level = _ROLE_LEVEL[override]
    else:
        eff_role = user.role
        eff_level = user.level

    # Candidate doc ids under the effective role.
    allowed_docs = [
        d for d in store.list_documents() if doc_is_visible_to(d, eff_role, eff_level)
    ]
    allowed_ids = [d.doc_id for d in allowed_docs]
    if not allowed_ids:
        return TraceResponse(
            query=q, role=eff_role, level=eff_level,
            dense=[], bm25=[], rrf=[], rerank=[], latency_ms=0,
        )

    t0 = time.perf_counter()
    dense = _dense_search(q, allowed_ids, k=10, max_doc_level=eff_level)
    bm25 = _bm25_search(q, allowed_ids, k=10, max_doc_level=eff_level)
    fused = _rrf_fuse(dense, bm25, k=settings.RRF_K)[:10]
    reranked = _rerank(q, fused, top_n=req.top_k)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    def pack_stage(hits, score_fn):
        out = []
        for hit in hits:
            meta = hit[1]
            did = meta.get("doc_id", "")
            cid = f"chunk:{did}:{meta.get('chunk_index', 0)}"
            out.append(TraceStageHit(chunk_id=cid, doc_id=did, score=float(score_fn(hit))))
        return out

    return TraceResponse(
        query=q,
        role=eff_role,
        level=eff_level,
        dense=pack_stage(dense, lambda h: h[2]),
        bm25=pack_stage(bm25, lambda h: h[2]),
        rrf=pack_stage(fused, lambda h: h[2]),
        rerank=[
            TraceStageHit(
                chunk_id=f"chunk:{m.get('doc_id','')}:{m.get('chunk_index', 0)}",
                doc_id=m.get("doc_id", ""),
                score=float(rerank_s),
            )
            for (_text, m, _rrf, rerank_s) in reranked
        ],
        latency_ms=latency_ms,
    )
