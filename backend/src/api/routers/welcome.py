"""Role-aware welcome endpoint + shared payload builder.

The same payload powers two surfaces:
  - GET /api/welcome — first-paint greeting in the empty chat state.
  - The `welcome` SSE event emitted by /api/chat when the user sends a
    social input (hello / thanks / "what can you do?"). This short-circuits
    retrieval so a greeting is never treated like an unanswerable query.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.auth.dependencies import CurrentUser, get_current_user
from src.core import store

router = APIRouter(prefix="/api", tags=["welcome"])


_LEVEL_LABELS = {1: "PUBLIC", 2: "INTERNAL", 3: "CONFIDENTIAL", 4: "RESTRICTED"}
_LEVEL_DESCRIPTIONS = {
    1: "Company-wide policies, onboarding handbook, training catalog.",
    2: "Engineering runbooks, process docs, internal announcements.",
    3: "Financial summaries, board minutes, leadership decisions.",
    4: "Security incidents, salary structures, executive-only reports.",
}

# Role-aware example prompts. Each is known to return grounded answers at
# that clearance level against the seeded TechNova corpus. Higher roles
# inherit suggestions from lower roles (plus their own).
_ROLE_SUGGESTIONS: dict[int, list[str]] = {
    1: [
        "What training is mandatory every year?",
        "Summarize the company's anti-bribery policy.",
        "What does the employee handbook say about code of conduct?",
        "What is the whistleblower policy?",
    ],
    2: [
        "What is the on-call rotation?",
        "What are the coding standards for new services?",
        "Summarize the incident response runbook.",
    ],
    3: [
        "Summarize Q4 revenue.",
        "What were the key takeaways from the latest board minutes?",
        "What was the departmental budget utilization last quarter?",
    ],
    4: [
        "What was the November security incident?",
        "What are the salary bands at TechNova?",
        "Summarize the most recent executive-only regulatory report.",
    ],
}


def _suggestions_for(level: int) -> list[str]:
    """Pick up to 5 example prompts spanning the user's accessible tiers."""
    out: list[str] = []
    for lvl in range(1, min(level, 4) + 1):
        out.extend(_ROLE_SUGGESTIONS.get(lvl, []))
    return out[:5]


def build_welcome_payload(user: CurrentUser) -> dict:
    """Role-aware greeting payload.

    Counts documents by classification the caller is cleared to see, picks
    example questions that will actually return grounded answers at their
    level, and emits the canonical role/clearance labels the UI renders.
    """
    visible_docs = [d for d in store.list_documents() if int(d.doc_level or 1) <= user.level]
    by_level: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    for d in visible_docs:
        lvl = int(d.doc_level or 1)
        by_level[lvl] = by_level.get(lvl, 0) + 1

    tiers = [
        {
            "level": lvl,
            "label": _LEVEL_LABELS[lvl],
            "description": _LEVEL_DESCRIPTIONS[lvl],
            "count": by_level.get(lvl, 0),
            "accessible": lvl <= user.level,
        }
        for lvl in (1, 2, 3, 4)
    ]

    role_title_map = {
        "guest": "Intern / Guest",
        "employee": "Employee",
        "manager": "Manager",
        "executive": "Executive",
    }

    return {
        "user": {
            "username": user.username,
            "role": user.role,
            "role_title": role_title_map.get(user.role, user.role.title()),
            "level": user.level,
            "clearance_label": _LEVEL_LABELS.get(user.level, "PUBLIC"),
        },
        "accessible_count": len(visible_docs),
        "tiers": tiers,
        "suggestions": _suggestions_for(user.level),
        "upload_hint": (
            f"You can upload documents classified from PUBLIC up to "
            f"{_LEVEL_LABELS.get(user.level, 'PUBLIC')} in the Knowledge tab."
        ),
        "greeting": _greeting_for(user),
    }


def _greeting_for(user: CurrentUser) -> str:
    name = user.username.strip() or "there"
    role = _LEVEL_LABELS.get(user.level, "PUBLIC")
    return (
        f"Hi {name} — you're signed in as {role} (L{user.level}). "
        f"I'm your Prism RAG assistant. Ask anything about the documents "
        f"you're cleared to see, or pick a suggestion below to start."
    )


@router.get("/welcome")
async def get_welcome(user: CurrentUser = Depends(get_current_user)) -> dict:
    return build_welcome_payload(user)
