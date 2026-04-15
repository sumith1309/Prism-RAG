from fastapi import APIRouter, Depends, HTTPException, Query
from qdrant_client.http import models as qm

from src.auth.dependencies import CurrentUser, get_current_user
from src.config import settings
from src.core import store
from src.pipelines.embedding_pipeline import get_qdrant
from src.pipelines.generation_pipeline import generate_suggested_questions

router = APIRouter(prefix="/api", tags=["meta"])


_DEFAULT_QUESTIONS = [
    "What topics does this document cover?",
    "Summarize the key points.",
    "What definitions are given?",
    "What are the most important numbers or dates?",
    "What actions or rules are required?",
    "What exceptions are mentioned?",
]


@router.get("/health")
async def health():
    import os

    qdrant_ok = True
    try:
        get_qdrant().get_collection(settings.QDRANT_COLLECTION)
    except Exception:
        qdrant_ok = False
    # Which LLM is actually in use? If LLM_BASE_URL is set, the OpenAI-compatible
    # path wins and LLM_MODEL is authoritative. Otherwise the HF chat model is used.
    use_openai = bool(os.environ.get("LLM_BASE_URL"))
    active_model = (
        os.environ.get("LLM_MODEL") if use_openai else settings.HF_CHAT_MODEL
    ) or "unknown"
    backend = "openai-compatible" if use_openai else "huggingface"
    return {
        "status": "ok" if qdrant_ok else "degraded",
        "qdrant": "ok" if qdrant_ok else "error",
        "qdrant_url": settings.QDRANT_URL,
        "llm_backend": backend,
        "chat_model": active_model,
        "hf_token_configured": bool(settings.HUGGINGFACEHUB_API_TOKEN),
        "embedding_model": settings.EMBED_MODEL,
        "reranker_model": settings.RERANK_MODEL,
    }


@router.get("/suggested-questions")
async def suggested_questions(
    doc_id: str = Query(...),
    user: CurrentUser = Depends(get_current_user),
):
    doc = store.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="document not found")
    if int(doc.doc_level or 1) > user.level:
        raise HTTPException(status_code=403, detail="document is above your clearance")

    excerpts = ""
    try:
        client = get_qdrant()
        points, _ = client.scroll(
            settings.QDRANT_COLLECTION,
            scroll_filter=qm.Filter(
                must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]
            ),
            limit=6,
            with_payload=True,
        )
        excerpts = "\n\n".join(str((p.payload or {}).get("text", "")) for p in points)
    except Exception:
        excerpts = ""
    if not excerpts:
        return {"questions": _DEFAULT_QUESTIONS}
    qs = await generate_suggested_questions(excerpts)
    if not qs:
        qs = _DEFAULT_QUESTIONS
    return {"questions": qs}


@router.get("/config")
async def get_config():
    return {
        "chunk_size": settings.CHUNK_SIZE,
        "chunk_overlap": settings.CHUNK_OVERLAP,
        "dense_top_k": settings.DENSE_TOP_K,
        "bm25_top_k": settings.BM25_TOP_K,
        "rrf_k": settings.RRF_K,
        "rerank_top_n": settings.RERANK_TOP_N,
        "rerank_candidates": settings.RERANK_CANDIDATES,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "chat_model": settings.HF_CHAT_MODEL,
        "embedding_model": settings.EMBED_MODEL,
        "reranker_model": settings.RERANK_MODEL,
    }
