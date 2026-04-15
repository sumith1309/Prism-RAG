"""Document routes with clearance-capped uploads.

- GET /api/documents      — any signed-in user; filtered to docs ≤ user.level.
- POST /api/documents     — any signed-in user; classification (1..user.level),
                            defaults to user.level. Uploading above your own
                            clearance returns 400.
- DELETE /api/documents/.. — manager+ (level >= 3). Guards sir's seeded corpus.
"""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from src.auth.dependencies import CurrentUser, get_current_user, require_level
from src.config import settings
from src.core import store
from src.core.schemas import DocumentMeta, UploadResponse, VisibilityUpdate
from src.pipelines.embedding_pipeline import delete_doc, ingest_file, set_doc_level
from src.pipelines.loaders import SUPPORTED_EXTS

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
    """Upload with clearance cap: 1 <= classification <= user.level; default = user.level.

    ``disabled_for_roles`` (exec-only, comma-separated) lets the exec set
    per-role visibility at upload time. Silently dropped for non-exec
    users — they can't control visibility beyond clearance anyway.
    """
    desired_level = int(classification) if classification is not None else int(user.level)
    if desired_level < 1 or desired_level > int(user.level):
        raise HTTPException(
            status_code=400,
            detail=(
                f"classification must be between 1 and your clearance level "
                f"({user.level}); got {desired_level}."
            ),
        )
    # Parse + filter disabled_for_roles — only honored for exec uploads.
    disable_set: list[str] = []
    if disabled_for_roles and user.role == "executive":
        disable_set = [
            r.strip().lower()
            for r in disabled_for_roles.split(",")
            if r.strip().lower() in _TOGGLABLE_ROLES
        ]

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
    return out


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, _user: CurrentUser = Depends(require_level(3))):
    if not delete_doc(doc_id):
        raise HTTPException(status_code=404, detail="document not found")
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
    return _to_meta(final)
