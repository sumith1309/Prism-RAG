"""Document routes with clearance-capped uploads.

- GET /api/documents      — any signed-in user; filtered to docs ≤ user.level.
- POST /api/documents     — any signed-in user; classification (1..user.level),
                            defaults to user.level. Uploading above your own
                            clearance returns 400.
- POST /api/documents/auto-classify — Tier 2.3: LLM suggests a clearance level
                            from the file's first 1500 chars. Frontend uses
                            the suggestion to pre-fill the picker.
- DELETE /api/documents/.. — manager+ (level >= 3). Guards sir's seeded corpus.
"""

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.auth.dependencies import CurrentUser, get_current_user, require_level
from src.config import settings
from src.core import chat_cache, store
from src.core.prompts import DOC_CLASSIFY_PROMPT
from src.core.schemas import DocumentMeta, UploadResponse, VisibilityUpdate
from src.pipelines.embedding_pipeline import delete_doc, ingest_file, set_doc_level
from src.pipelines.generation_pipeline import _complete_chat
from src.pipelines.loaders import SUPPORTED_EXTS, load_any

router = APIRouter(prefix="/api/documents", tags=["documents"])


_LEVEL_LABELS = {1: "PUBLIC", 2: "INTERNAL", 3: "CONFIDENTIAL", 4: "RESTRICTED"}


def _to_meta(d: store.Document) -> DocumentMeta:
    level = int(d.doc_level or 1)
    return DocumentMeta(
        doc_id=d.doc_id,
        filename=d.filename,
        mime=d.mime,
        pages=d.pages,
        chunks=d.chunks,
        sections=[s for s in d.sections.split(",") if s],
        doc_level=level,
        classification=_LEVEL_LABELS.get(level, "PUBLIC"),
        created_at=d.created_at,
        uploaded_by_username=d.uploaded_by_username or "",
        uploaded_by_role=d.uploaded_by_role or "",
        disabled_for_roles=[r for r in (d.disabled_for_roles or "").split(",") if r],
    )


@router.get("", response_model=list[DocumentMeta])
async def list_docs(user: CurrentUser = Depends(get_current_user)):
    """Return documents the caller is cleared to see, respecting the exec's
    per-role disable list. Exec (L4) sees every document — including those
    they've disabled for lower roles — so they can re-enable them."""
    return [
        _to_meta(d)
        for d in store.list_documents()
        if store.doc_is_visible_to(d, user.role, user.level)
    ]


@router.post("", response_model=list[UploadResponse])
async def upload_docs(
    files: list[UploadFile] = File(...),
    classification: Optional[int] = Form(default=None),
    disabled_for_roles: Optional[str] = Form(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload with visibility escalation: non-exec uploads are auto-
    elevated so the executive reviews them first.

    Escalation rules:
      - Guest/Intern uploads → RESTRICTED (L4, exec only)
      - Employee uploads     → CONFIDENTIAL (L3, manager + exec)
      - Manager uploads      → RESTRICTED (L4, exec only)
      - Executive uploads    → whatever they choose (unchanged)

    Exec can then reclassify downward via PATCH /visibility once they've
    reviewed the content. This prevents a guest from uploading a doc
    that ALL other guests can immediately see without review.

    ``disabled_for_roles`` (exec-only, comma-separated) lets the exec set
    per-role visibility at upload time. Silently dropped for non-exec
    users — they can't control visibility beyond clearance anyway.
    """
    # Upload visibility: uploader sees their own doc + exec always sees it.
    # Everyone else is blocked via disabled_for_roles until exec shares.
    _ALL_NON_EXEC_ROLES = {"guest", "employee", "manager"}
    if user.role == "executive":
        # Exec chooses freely — no restrictions.
        desired_level = int(classification) if classification is not None else int(user.level)
        if desired_level < 1 or desired_level > 4:
            raise HTTPException(
                status_code=400,
                detail=f"classification must be between 1 and 4; got {desired_level}.",
            )
    else:
        # Non-exec: doc_level = uploader's own level (so they can see it).
        # disabled_for_roles = everyone except uploader's role + exec.
        desired_level = int(user.level)

    # Build the disable list:
    #   Exec: from the form field (they choose explicitly).
    #   Non-exec: auto-hide from all other non-exec roles so only the
    #   uploader + exec can see the doc until exec shares it wider.
    disable_set: list[str] = []
    if user.role == "executive":
        if disabled_for_roles:
            disable_set = [
                r.strip().lower()
                for r in disabled_for_roles.split(",")
                if r.strip().lower() in _TOGGLABLE_ROLES
            ]
    else:
        disable_set = sorted(_ALL_NON_EXEC_ROLES - {user.role})

    out: list[UploadResponse] = []
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTS:
            out.append(
                UploadResponse(
                    doc_id="",
                    filename=f.filename or "",
                    status="error",
                    error=f"Unsupported type {ext}",
                )
            )
            continue
        contents = await f.read()
        if len(contents) > max_bytes:
            out.append(
                UploadResponse(
                    doc_id="",
                    filename=f.filename or "",
                    status="error",
                    error=f"File exceeds {settings.MAX_UPLOAD_MB} MB",
                )
            )
            continue
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(contents)
            tmp_path = Path(tmp.name)
        try:
            doc = ingest_file(
                tmp_path,
                original_filename=f.filename or tmp_path.name,
                doc_level=desired_level,
                uploaded_by_username=user.username,
                uploaded_by_role=user.role,
            )
            if disable_set:
                store.set_disabled_roles(doc.doc_id, disable_set)
            out.append(
                UploadResponse(
                    doc_id=doc.doc_id,
                    filename=doc.filename,
                    status="ok",
                    chunks=doc.chunks,
                    pages=doc.pages,
                )
            )
        except Exception as e:
            out.append(
                UploadResponse(
                    doc_id="",
                    filename=f.filename or "",
                    status="error",
                    error=f"{type(e).__name__}: {e}",
                )
            )
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
    # Tier 1.2 — bust the entire chat cache after upload(s). Otherwise
    # a previous "no confident answer" or "general knowledge" cached
    # response would replay even though the new doc could now answer
    # that exact query. Cache is small (≤512 entries), so a full clear
    # on upload is cheap.
    if any(o.status == "ok" for o in out):
        chat_cache.bust_all()
    return out


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, _user: CurrentUser = Depends(require_level(3))):
    if not delete_doc(doc_id):
        raise HTTPException(status_code=404, detail="document not found")
    # Tier 1.2 — bust any cached chat answers that cited this doc so the
    # deletion takes effect on subsequent identical queries.
    chat_cache.bust_for_doc(doc_id)
    return {"ok": True}


_TOGGLABLE_ROLES = {"guest", "employee", "manager"}


@router.patch("/{doc_id}/visibility", response_model=DocumentMeta)
async def update_visibility(
    doc_id: str,
    req: VisibilityUpdate,
    _user: CurrentUser = Depends(require_level(4)),
):
    """Exec-only atomic visibility update. Accepts either or both fields:

    - ``disabled_for_roles`` — which non-exec roles should be hidden.
    - ``doc_level`` — reclassify the doc (1..4). Rewrites Qdrant + BM25
      metadata so retrieval picks up the new level without re-ingest.

    At least one field must be present. The frontend uses this to express
    "visible to these roles" as a single atomic change: it picks the right
    ``doc_level`` (clearance floor) and ``disabled_for_roles`` (hide list)
    in one shot.
    """
    if req.disabled_for_roles is None and req.doc_level is None:
        raise HTTPException(
            status_code=400,
            detail="must provide disabled_for_roles and/or doc_level",
        )

    if req.doc_level is not None:
        if req.doc_level < 1 or req.doc_level > 4:
            raise HTTPException(
                status_code=400,
                detail=f"doc_level must be between 1 and 4; got {req.doc_level}",
            )
        updated = set_doc_level(doc_id, req.doc_level)
        if updated is None:
            raise HTTPException(status_code=404, detail="document not found")

    if req.disabled_for_roles is not None:
        dirty = [r.strip().lower() for r in req.disabled_for_roles]
        clean = [r for r in dirty if r in _TOGGLABLE_ROLES]
        updated = store.set_disabled_roles(doc_id, clean)
        if updated is None:
            raise HTTPException(status_code=404, detail="document not found")

    # Final state (at least one mutation ran — grab the fresh row).
    final = store.get_document(doc_id)
    if final is None:
        raise HTTPException(status_code=404, detail="document not found")
    # Tier 1.2 — bust the chat cache for this doc so cached answers
    # don't replay with the OLD clearance / OLD hide-list. Without this
    # a guest could keep getting a cached answer that included a chunk
    # the exec just promoted to RESTRICTED.
    chat_cache.bust_for_doc(doc_id)
    return _to_meta(final)


# ─── Tier 2.3 — Auto-tag classifier ────────────────────────────────────────


class AutoClassifyResponse(BaseModel):
    suggested_level: int
    suggested_label: str
    reason: str
    confidence: float
    capped_to_user_level: bool  # true if suggestion was clipped to user.level


async def _suggest_doc_level(filename: str, excerpt: str) -> dict:
    """LLM-based clearance classifier. Returns {level, reason, confidence}.

    Defaults to L2 INTERNAL on parse failure (the most common safe class
    for unidentified business docs). Conservative bias is baked into the
    prompt: "when in doubt, classify higher".
    """
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [
                    {
                        "role": "user",
                        "content": DOC_CLASSIFY_PROMPT.format(
                            filename=filename[:120],
                            excerpt=(excerpt or "")[:1500],
                        ),
                    }
                ],
                max_tokens=150,
                temperature=0.0,
            ),
            timeout=10.0,
        )
        s = (txt or "").strip()
        # Strip markdown fences if the model wraps them despite our instruction.
        if s.startswith("```"):
            s = s.strip("`").strip()
            if s.startswith("json"):
                s = s[4:].strip()
        parsed = json.loads(s)
        level = int(parsed.get("level", 2))
        if level < 1 or level > 4:
            level = 2
        return {
            "level": level,
            "reason": str(parsed.get("reason", "")).strip()[:240]
                or "Best guess based on content + filename.",
            "confidence": float(parsed.get("confidence", 0.6)),
        }
    except Exception:
        return {
            "level": 2,
            "reason": "Classifier unavailable — defaulting to INTERNAL.",
            "confidence": 0.4,
        }


@router.post("/auto-classify", response_model=AutoClassifyResponse)
async def auto_classify(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    """Pre-upload preview: takes a file, returns the LLM's suggested
    clearance level + reason + confidence. The frontend uses this to
    pre-fill the classification picker so the user doesn't have to
    guess. Suggestion is always capped at the caller's clearance — a
    guest never sees a "suggested: RESTRICTED" prompt they can't act on.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400, detail=f"Unsupported type {ext}"
        )
    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB",
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    excerpt = ""
    try:
        raw_docs = load_any(tmp_path)
        for d in raw_docs:
            excerpt += (d.page_content or "") + "\n"
            if len(excerpt) > 3000:
                break
    except Exception:
        excerpt = ""
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    if not excerpt.strip():
        # No text extracted (scanned PDF / corrupt). Suggest user's own
        # level as a safe default rather than guessing.
        return AutoClassifyResponse(
            suggested_level=user.level,
            suggested_label=_LEVEL_LABELS.get(user.level, "INTERNAL"),
            reason="Could not extract text — defaulting to your clearance.",
            confidence=0.3,
            capped_to_user_level=True,
        )

    suggestion = await _suggest_doc_level(file.filename or "", excerpt)
    raw_level = suggestion["level"]
    capped_level = min(raw_level, user.level)
    return AutoClassifyResponse(
        suggested_level=capped_level,
        suggested_label=_LEVEL_LABELS.get(capped_level, "INTERNAL"),
        reason=suggestion["reason"],
        confidence=suggestion["confidence"],
        capped_to_user_level=(capped_level != raw_level),
    )
