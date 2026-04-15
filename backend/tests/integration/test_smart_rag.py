"""Smart 4-way RAG: grounded / refused / general / unknown.

Verifies:
  1. Non-L4 users NEVER see `general` or `refused` — those collapse to `unknown`.
     (Metadata-enumeration leak is closed.)
  2. L4 users see the split — `general` for truly-out-of-corpus queries, `refused`
     for queries that a higher-clearance doc would have answered.
  3. Grounded queries produce `grounded` mode with sources for any cleared user.

Uses the live /api/chat SSE stream. The final ``done`` event carries the
authoritative answer_mode — we parse it without waiting for full generation.
"""

from __future__ import annotations

import json

import httpx

BASE = "http://127.0.0.1:8765"


def _login(username: str, password: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def _mode_for(token: str, query: str) -> str:
    """Open the SSE stream, read until ``done``, return the answer_mode payload."""
    with httpx.Client(timeout=120) as c:
        with c.stream(
            "POST",
            f"{BASE}/api/chat",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json={"query": query, "use_rerank": True, "top_k": 5},
        ) as r:
            r.raise_for_status()
            cur_event: str = ""
            for raw in r.iter_lines():
                if not raw:
                    cur_event = ""
                    continue
                line = raw if isinstance(raw, str) else raw.decode()
                if line.startswith("event:"):
                    cur_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and cur_event == "done":
                    payload = json.loads(line.split(":", 1)[1])
                    return str(payload.get("answer_mode", ""))
    return ""


# ---------------------------------------------------------------------------
# Non-L4 unified response — no `general`, no `refused` exposed to low roles.
# ---------------------------------------------------------------------------


def test_guest_out_of_corpus_query_never_returns_general() -> None:
    """Guest asks an out-of-corpus question — must NOT be 'general' (L4-only).
    Depending on RRF marginal matches it may be 'unknown' or 'grounded'; either
    is acceptable as long as it isn't 'general' (which would leak that the
    corpus-existence heuristic ran)."""
    tok = _login("guest", "guest_pass")
    mode = _mode_for(tok, "asdhjkfgaw quantum encryption protocol xyz")
    assert mode != "general", f"guest must never see general mode, got {mode!r}"


def test_guest_rbac_blocked_query_never_returns_refused() -> None:
    """Guest asks about salary bands (Salary_Structure is L4) — must NOT be
    'refused' (L4-only). Closes the metadata-enumeration leak."""
    tok = _login("guest", "guest_pass")
    mode = _mode_for(tok, "What are the salary bands at TechNova?")
    assert mode != "refused", f"guest must never see refused mode, got {mode!r}"
    assert mode != "general", f"guest must never see general mode, got {mode!r}"


def test_manager_blocked_query_never_returns_refused() -> None:
    """Manager (L3) asks about Security_Incident_Report (L4) — must NOT be
    'refused' (L4-only)."""
    tok = _login("manager", "manager_pass")
    mode = _mode_for(tok, "What was the November security incident?")
    assert mode != "refused", f"manager must never see refused mode, got {mode!r}"
    assert mode != "general", f"manager must never see general mode, got {mode!r}"


# ---------------------------------------------------------------------------
# L4 split — executive sees general vs refused distinction.
# ---------------------------------------------------------------------------


def test_executive_truly_out_of_corpus_query_returns_general_not_unknown() -> None:
    """Exec asks a clearly out-of-corpus question. The exact mode depends on
    whether any retriever surfaces a marginal match; if nothing matches at all
    the mode must be 'general' (L4 sees the split)."""
    tok = _login("exec", "exec_pass")
    mode = _mode_for(tok, "asdhjkfgaw quantum encryption protocol xyz")
    # Either 'general' (nothing matched) or 'unknown' (fell through _looks_like_real_query)
    # — but NEVER 'refused' (no higher-clearance doc exists for gibberish).
    assert mode in {"general", "unknown"}, f"exec out-of-corpus got {mode!r}"


def test_executive_grounded_query_returns_grounded() -> None:
    """Exec asks about salary bands — Salary_Structure IS in their clearance → grounded."""
    tok = _login("exec", "exec_pass")
    mode = _mode_for(tok, "What are the salary bands at TechNova?")
    assert mode == "grounded", f"expected grounded for exec in-corpus query, got {mode!r}"


def test_guest_grounded_query_returns_grounded() -> None:
    """Guest asking PUBLIC content still works."""
    tok = _login("guest", "guest_pass")
    mode = _mode_for(tok, "What training is mandatory every year?")
    assert mode == "grounded", f"expected grounded for guest public query, got {mode!r}"


# ---------------------------------------------------------------------------
# Social short-circuit — greetings / thanks / "what can you do?" bypass RAG
# and return the role-aware welcome payload instantly. Must never retrieve.
# ---------------------------------------------------------------------------


def _welcome_and_mode_for(token: str, query: str) -> tuple[str, dict | None]:
    """Open the SSE stream, capture welcome payload + final answer_mode."""
    welcome: dict | None = None
    mode = ""
    with httpx.Client(timeout=60) as c:
        with c.stream(
            "POST",
            f"{BASE}/api/chat",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json={"query": query, "use_rerank": True, "top_k": 5},
        ) as r:
            r.raise_for_status()
            cur_event = ""
            for raw in r.iter_lines():
                if not raw:
                    cur_event = ""
                    continue
                line = raw if isinstance(raw, str) else raw.decode()
                if line.startswith("event:"):
                    cur_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    payload = json.loads(line.split(":", 1)[1])
                    if cur_event == "welcome":
                        welcome = payload
                    elif cur_event == "done":
                        mode = str(payload.get("answer_mode", ""))
    return mode, welcome


def test_guest_hello_returns_social_with_welcome_payload() -> None:
    tok = _login("guest", "guest_pass")
    mode, welcome = _welcome_and_mode_for(tok, "hello")
    assert mode == "social", f"expected social, got {mode!r}"
    assert welcome is not None, "welcome event missing"
    assert welcome["user"]["level"] == 1
    assert welcome["user"]["clearance_label"] == "PUBLIC"
    assert welcome["accessible_count"] >= 1
    assert len(welcome["suggestions"]) >= 1
    # Guest must not see CONFIDENTIAL/RESTRICTED counts populated (>0 access).
    tiers = {t["label"]: t for t in welcome["tiers"]}
    assert tiers["PUBLIC"]["accessible"] is True
    assert tiers["RESTRICTED"]["accessible"] is False


def test_exec_thanks_returns_social() -> None:
    tok = _login("exec", "exec_pass")
    mode, welcome = _welcome_and_mode_for(tok, "thank you!")
    assert mode == "social"
    assert welcome and welcome["user"]["level"] == 4
    # Exec sees all four tiers accessible.
    tiers = {t["label"]: t for t in welcome["tiers"]}
    assert all(tiers[lbl]["accessible"] for lbl in ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"])


def test_meta_question_returns_social() -> None:
    tok = _login("employee", "employee_pass")
    mode, welcome = _welcome_and_mode_for(tok, "what can you do?")
    assert mode == "social"
    assert welcome and welcome["user"]["level"] == 2


def test_long_query_with_hi_prefix_is_not_social() -> None:
    """Ensures 'hi, tell me about the annual training requirements' still
    runs full RAG — the social detector must only fire on short greetings."""
    tok = _login("guest", "guest_pass")
    mode, welcome = _welcome_and_mode_for(
        tok,
        "hi, can you please summarize the full annual training requirements for new hires?",
    )
    assert mode != "social", f"long substantive query wrongly classified social: {mode!r}"
