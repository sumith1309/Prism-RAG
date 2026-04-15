"""Per-user chat thread CRUD.

Every endpoint is gated on ``get_current_user``; threads are strictly scoped
to the caller (``user_id`` check inside every helper), so user A can never
read, rename, or delete user B's threads.
"""

import json

from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import CurrentUser, get_current_user
from src.core import models
from src.core.schemas import RenameRequest, ThreadDetail, ThreadSummary, ThreadTurn

router = APIRouter(prefix="/api/threads", tags=["threads"])


def _to_summary(t: models.ChatThread) -> ThreadSummary:
    return ThreadSummary(id=t.id, title=t.title, created_at=t.created_at, updated_at=t.updated_at)


@router.get("", response_model=list[ThreadSummary])
def list_my_threads(user: CurrentUser = Depends(get_current_user)):
    return [_to_summary(t) for t in models.list_threads(user.id)]


@router.post("", response_model=ThreadSummary)
def create_my_thread(user: CurrentUser = Depends(get_current_user)):
    t = models.create_thread(user.id, title="New chat")
    return _to_summary(t)


@router.get("/{thread_id}", response_model=ThreadDetail)
def get_my_thread(thread_id: str, user: CurrentUser = Depends(get_current_user)):
    t = models.get_thread(thread_id, user.id)
    if t is None:
        raise HTTPException(status_code=404, detail="thread not found")

    turns_out: list[ThreadTurn] = []
    for r in models.list_turns(thread_id):
        try:
            sources = json.loads(r.sources_json) if r.sources_json else []
        except Exception:
            sources = []
        turns_out.append(
            ThreadTurn(
                id=int(r.id or 0),
                role=r.role,
                content=r.content,
                sources=sources,
                refused=bool(r.refused),
                answer_mode=r.answer_mode or "grounded",
                faithfulness=float(getattr(r, "faithfulness", -1.0) or -1.0),
                created_at=r.created_at,
            )
        )
    return ThreadDetail(
        id=t.id,
        title=t.title,
        created_at=t.created_at,
        updated_at=t.updated_at,
        turns=turns_out,
    )


@router.patch("/{thread_id}", response_model=ThreadSummary)
def rename_my_thread(
    thread_id: str,
    req: RenameRequest,
    user: CurrentUser = Depends(get_current_user),
):
    title = (req.title or "").strip()[:120]
    if not title:
        raise HTTPException(status_code=400, detail="title must not be empty")
    t = models.rename_thread(thread_id, user.id, title)
    if t is None:
        raise HTTPException(status_code=404, detail="thread not found")
    return _to_summary(t)


@router.delete("/{thread_id}")
def delete_my_thread(thread_id: str, user: CurrentUser = Depends(get_current_user)):
    if not models.delete_thread(thread_id, user.id):
        raise HTTPException(status_code=404, detail="thread not found")
    return {"ok": True}
