"""Hybrid retrieval — dense (Qdrant) + BM25 (pickle-per-doc) + RRF fusion + optional cross-encoder rerank.

The RBAC filter is applied at the Qdrant `where` clause (and mirrored in BM25
result post-filtering) so chunks above the caller's clearance are *physically
unreachable*. The LLM never sees them — no prompt-injection can exfiltrate.
"""

import pickle
import re
from typing import Optional

from qdrant_client.http import models as qm

from src.config import settings
from src.core import store
from src.core.schemas import RetrievedChunk
from src.pipelines.embedding_pipeline import _get_embeddings, get_qdrant


_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(settings.RERANK_MODEL, device="cpu")
    return _reranker


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _load_bm25(doc_id: str):
    path = settings.abs(settings.EMBEDDINGS_DIR) / f"{doc_id}.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def _build_filter(doc_ids: list[str], max_doc_level: Optional[int]) -> Optional[qm.Filter]:
    must: list[qm.Condition] = []
    if doc_ids:
        must.append(qm.FieldCondition(key="doc_id", match=qm.MatchAny(any=list(doc_ids))))
    if max_doc_level is not None:
        must.append(qm.FieldCondition(key="doc_level", range=qm.Range(lte=int(max_doc_level))))
    return qm.Filter(must=must) if must else None


def _dense_search(
    query: str,
    doc_ids: list[str],
    k: int,
    max_doc_level: Optional[int],
) -> list[tuple[str, dict, float]]:
    """Returns [(text, metadata, score), ...] — score is cosine similarity (higher is better)."""
    client = get_qdrant()
    qvec = _get_embeddings().embed_query(query)
    flt = _build_filter(doc_ids, max_doc_level)
    results = client.query_points(
        settings.QDRANT_COLLECTION,
        query=qvec,
        limit=k,
        query_filter=flt,
        with_payload=True,
    ).points
    out: list[tuple[str, dict, float]] = []
    for r in results:
        p = r.payload or {}
        text = str(p.get("text", ""))
        meta = {
            "doc_id": p.get("doc_id", ""),
            "filename": p.get("filename", ""),
            "page": int(p.get("page", 0) or 0),
            "section": p.get("section", "") or "",
            "chunk_index": int(p.get("chunk_index", 0) or 0),
            "doc_level": int(p.get("doc_level", 1) or 1),
        }
        out.append((text, meta, float(r.score)))
    return out


def _bm25_search(
    query: str,
    doc_ids: list[str],
    k: int,
    max_doc_level: Optional[int],
) -> list[tuple[str, dict, float]]:
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []
    all_hits: list[tuple[str, dict, float]] = []
    for doc_id in doc_ids:
        bundle = _load_bm25(doc_id)
        if not bundle or bundle.get("bm25") is None:
            continue
        bm25 = bundle["bm25"]
        texts = bundle["texts"]
        metas = bundle["meta"]
        scores = bm25.get_scores(q_tokens)
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        for idx in ranked:
            if scores[idx] <= 0:
                continue
            meta = metas[idx]
            if max_doc_level is not None and int(meta.get("doc_level", 1)) > int(max_doc_level):
                continue
            all_hits.append((texts[idx], meta, float(scores[idx])))
    all_hits.sort(key=lambda t: -t[2])
    return all_hits[:k]


def _rrf_fuse(dense: list, bm25: list, k: int = 60) -> list[tuple[str, dict, float]]:
    """Reciprocal Rank Fusion: score = sum(1 / (k + rank))."""
    fused: dict[str, dict] = {}

    def key(meta: dict, text: str) -> str:
        return f"{meta.get('doc_id','')}:{meta.get('chunk_index', text[:40])}"

    for rank, (text, meta, _score) in enumerate(dense):
        kid = key(meta, text)
        fused.setdefault(kid, {"text": text, "meta": meta, "score": 0.0})
        fused[kid]["score"] += 1.0 / (k + rank + 1)

    for rank, (text, meta, _score) in enumerate(bm25):
        kid = key(meta, text)
        fused.setdefault(kid, {"text": text, "meta": meta, "score": 0.0})
        fused[kid]["score"] += 1.0 / (k + rank + 1)

    items = sorted(fused.values(), key=lambda v: -v["score"])
    return [(it["text"], it["meta"], it["score"]) for it in items]


def _rerank(query: str, candidates: list[tuple[str, dict, float]], top_n: int):
    if not candidates:
        return []
    reranker = _get_reranker()
    pairs = [[query, text] for text, _m, _s in candidates]
    scores = reranker.predict(pairs)
    scored = [
        (text, meta, rrf_score, float(rerank_score))
        for (text, meta, rrf_score), rerank_score in zip(candidates, scores)
    ]
    scored.sort(key=lambda x: -x[3])
    return scored[:top_n]


async def hyde_rewrite(query: str) -> str:
    """Use the HF chat model to draft a hypothetical answer; embed that instead of the raw query."""
    from src.pipelines.generation_pipeline import hyde_generate
    try:
        passage = await hyde_generate(query)
        if passage and len(passage) > 10:
            return f"{query}\n\n{passage}"
    except Exception:
        pass
    return query


async def retrieve(
    query: str,
    doc_ids: Optional[list[str]] = None,
    use_hyde: bool = False,
    use_rerank: bool = True,
    section_filter: Optional[list[str]] = None,
    top_k: int = 5,
    max_doc_level: Optional[int] = None,
    bypass_rbac: bool = False,
    caller_role: Optional[str] = None,
) -> list[RetrievedChunk]:
    """Retrieve top-k chunks for a query.

    If ``max_doc_level`` is set, chunks with ``doc_level > max_doc_level`` are
    filtered out at the vector-store layer (and in BM25 post-processing). This
    is how RBAC is enforced: the caller passes the user's level, and higher-
    clearance chunks never enter the LLM context.

    ``bypass_rbac=True`` disables the level filter entirely — used by the
    smart-RAG probe in chat.py to detect whether a query *would* have been
    answered by a higher-clearance document. Output of bypass-probes MUST NOT
    be returned to the user directly; it is only used to decide response mode.
    """
    effective_max_level = None if bypass_rbac else max_doc_level

    # Exec's per-role kill-switch: a doc disabled for the caller's role is
    # excluded from the candidate set before any search runs, independent of
    # clearance. The bypass-probe path (used to distinguish refused/general)
    # ignores this so the classifier can still detect higher-clearance hits.
    blocked_doc_ids: set[str] = set()
    if not bypass_rbac and caller_role and caller_role != "executive":
        blocked_doc_ids = {
            d.doc_id
            for d in store.list_documents()
            if caller_role in (d.disabled_for_roles or "").split(",")
        }

    if doc_ids is None:
        if effective_max_level is not None:
            doc_ids = [
                d.doc_id
                for d in store.list_documents()
                if int(d.doc_level) <= int(effective_max_level)
                and d.doc_id not in blocked_doc_ids
            ]
        else:
            doc_ids = [
                d.doc_id
                for d in store.list_documents()
                if d.doc_id not in blocked_doc_ids
            ]
    else:
        doc_ids = [d for d in doc_ids if d not in blocked_doc_ids]
    if not doc_ids:
        return []

    search_query = await hyde_rewrite(query) if use_hyde else query

    dense = _dense_search(search_query, doc_ids, k=settings.DENSE_TOP_K * 2, max_doc_level=effective_max_level)
    bm25 = _bm25_search(query, doc_ids, k=settings.BM25_TOP_K * 2, max_doc_level=effective_max_level)

    if section_filter:
        s_lower = {s.lower() for s in section_filter}
        dense = [d for d in dense if d[1].get("section", "").lower() in s_lower]
        bm25 = [d for d in bm25 if d[1].get("section", "").lower() in s_lower]

    fused = _rrf_fuse(dense, bm25, k=settings.RRF_K)
    top_candidates = fused[:20]

    if use_rerank and top_candidates:
        reranked = _rerank(query, top_candidates, top_n=top_k)
        return [
            RetrievedChunk(
                text=text,
                doc_id=meta.get("doc_id", ""),
                filename=meta.get("filename", ""),
                page=int(meta.get("page", 0) or 0),
                section=meta.get("section", "") or "",
                rrf_score=float(rrf_s),
                rerank_score=rerank_s,
                source_index=i,
            )
            for i, (text, meta, rrf_s, rerank_s) in enumerate(reranked, start=1)
        ]

    return [
        RetrievedChunk(
            text=text,
            doc_id=meta.get("doc_id", ""),
            filename=meta.get("filename", ""),
            page=int(meta.get("page", 0) or 0),
            section=meta.get("section", "") or "",
            rrf_score=float(rrf_s),
            rerank_score=None,
            source_index=i,
        )
        for i, (text, meta, rrf_s) in enumerate(top_candidates[:top_k], start=1)
    ]
