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
from src.core.schemas import DocumentMeta, UploadResponse
from src.pipelines.embedding_pipeline import delete_doc, ingest_file
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
    )


@router.get("", response_model=list[DocumentMeta])
async def list_docs(user: CurrentUser = Depends(get_current_user)):
    """Only return documents the caller is cleared to see."""
    return [_to_meta(d) for d in store.list_documents() if int(d.doc_level or 1) <= user.level]


@router.post("", response_model=list[UploadResponse])
async def upload_docs(
    files: list[UploadFile] = File(...),
    classification: Optional[int] = Form(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload with clearance cap: 1 <= classification <= user.level; default = user.level."""
    desired_level = int(classification) if classification is not None else int(user.level)
    if desired_level < 1 or desired_level > int(user.level):
        raise HTTPException(
            status_code=400,
            detail=(
                f"classification must be between 1 and your clearance level "
                f"({user.level}); got {desired_level}."
            ),
        )

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
            )
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
