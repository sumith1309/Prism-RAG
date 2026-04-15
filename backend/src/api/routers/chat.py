"""Role-gated streaming chat with smart 4-way answer modes.

Pipeline per request:
  1. Rate-limit check (60 chats/min/user).
  2. Cache lookup (sha1 of query+role+docs+settings). Cached = instant replay.
  3. Thread setup (load or create, emit ``thread`` event first).
  4. Optional multi-query rewrite (settings.useMultiQuery) → 3 LLM variants.
  5. Grounded retrieval with RBAC filter. Time-boxed.
  6. Relevance gate (RRF-first two-path rule).
  7. If weak → Corrective RAG: one LLM-rewritten retry before declaring miss.
  8. Still weak + real query → bypass probe; branch by mode (L4-only split).
  9. Generate (stream). Instrument retrieve/rerank/generate ms + tokens.
 10. Faithfulness verifier (grounded only) — LLM-scored 0..1, non-blocking.
 11. Persist turns + audit row with the full observability payload.
"""

import asyncio
import json
import time

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from src.api.routers.welcome import build_welcome_payload
from src.auth.dependencies import CurrentUser
from src.core import chat_cache, models
from src.core.prompts import (
    CONTEXTUALIZE_PROMPT,
    CORRECTIVE_PROMPT,
    FAITHFULNESS_PROMPT,
    GENERAL_SYSTEM_PROMPT,
    META_CONVERSATION_PROMPT,
    MULTI_QUERY_PROMPT,
    SYSTEM_INTEL_PROMPT,
    SYSTEM_PROMPT,
    TITLE_PROMPT,
    build_context_block,
    build_user_prompt,
)
from src.core.rate_limit import chat_rate_limit
from src.core.schemas import ChatRequest
from src.pipelines.generation_pipeline import _complete_chat, _stream_chat
from src.pipelines.retrieval_pipeline import retrieve

router = APIRouter(prefix="/api", tags=["chat"])


# --- relevance gate (RRF-first; rerank supplementary) -----------------------
STRONG_RRF = 0.024
STRONG_RERANK = 0.30
MEDIUM_RRF = 0.015
MEDIUM_RERANK = 0.05


def _looks_like_real_query(q: str) -> bool:
    """Permissive: accept any non-trivial query with actual letters.
    Rejects '', '  ', '!!!', '123' — but allows 'hello', 'AI', 'Q4'."""
    stripped = q.strip()
    return len(stripped) >= 2 and any(c.isalpha() for c in stripped)


def _is_substantive_query(q: str) -> bool:
    """Tighter guard for expensive operations (corrective rewrite, multi-query).
    Short social/greeting inputs like 'hello' don't need a rewrite probe."""
    tokens = [t for t in q.split() if len(t) >= 2 and any(c.isalpha() for c in t)]
    return len(tokens) >= 2


# Social inputs the agent should answer with a warm greeting instead of
# running retrieval. Kept small and high-precision — anything richer should
# go through RAG. Matched on the *whole* query (case-insensitive, trimmed).
_SOCIAL_EXACT = {
    "hi", "hii", "hiii", "hello", "helo", "hey", "heya", "yo", "sup", "hola",
    "namaste", "namaskar", "salaam", "salam", "howdy", "greetings",
    "good morning", "good afternoon", "good evening", "good night",
    "morning", "evening",
    "thanks", "thank you", "thanks!", "thank you!", "thx", "ty", "tysm",
    "appreciate it", "much appreciated",
    "bye", "goodbye", "see you", "cya", "later", "see ya",
    "ok", "okay", "cool", "nice", "great",
    "help", "?", "??", "???",
    "who are you", "who are you?", "what are you", "what are you?",
    "what can you do", "what can you do?", "what do you do", "what do you do?",
    "what do you know", "what do you know?", "how does this work",
    "how does this work?", "what is this", "what is this?",
    "tell me about yourself", "introduce yourself", "capabilities",
    "how can you help", "how can you help?", "how can you help me",
    "how can you help me?",
}

_SOCIAL_PREFIXES = (
    "hi ", "hii ", "hello ", "hey ", "heya ", "hola ", "namaste ",
    "good morning", "good afternoon", "good evening", "good night",
    "thanks ", "thank you", "thx ",
)


# Meta-conversation phrases — the user is asking about THIS chat itself
# ("what did I ask before?", "summarize our conversation", "what was your
# last answer") instead of the document corpus. Must be routed straight to
# generation with chat history, not through retrieval, or it collapses to
# "no confident answer" when the retriever finds nothing relevant.
_META_CONV_PHRASES = (
    "first question", "last question", "previous question", "earlier question",
    "my first", "my last", "my previous", "my earlier",
    "first answer", "last answer", "previous answer", "earlier answer",
    "your first", "your last", "your previous", "your earlier",
    "what did i ask", "what i asked", "what did you say", "what you said",
    "what did you answer", "what you answered",
    "what have we", "what did we", "have we discussed", "did we discuss",
    "summarize our", "summarize this chat", "summarize the chat",
    "summarize our conversation", "recap this chat", "recap our",
    "our conversation", "this conversation", "this chat",
    "what is this conversation", "what was the last",
    "what was i asking", "what was i talking",
    "go back to", "we were talking about", "what were we talking",
)


# System-intelligence phrases — the user is asking about platform USAGE
# (recent queries, top users, what people have asked), not about the
# document corpus. Routed straight to the audit log.
_SYSTEM_INTEL_PHRASES = (
    "recent queries", "recent activity", "recent question",
    "user queries", "queries by users", "queries asked by",
    "what users have asked", "what users asked", "what people asked",
    "what have users", "what did users", "show me activity",
    "user activity", "audit log", "audit data",
    "popular queries", "top queries", "common queries",
    "who has asked", "who asked", "who is using",
    "platform usage", "usage stats", "system stats", "system metrics",
    "how many queries", "total queries", "query count",
    "most active user", "top users", "active users",
    "query history", "query log",
    "refused queries", "refused requests",
    "average faithfulness", "cache hit",
    # Personal-scope variants — caller asks about THEIR OWN activity.
    # These also route to system-intel and the audit query is scoped by
    # user_id when the caller isn't an exec.
    "queries i have asked", "queries i asked",
    "queries have i asked", "queries i've asked",
    "questions i have asked", "questions i asked",
    "questions have i asked", "questions i've asked",
    "what queries have", "what questions have",
    "what have i asked", "what i have asked", "what i asked",
    "have i asked", "did i ask",
    "my recent queries", "my recent questions",
    "my queries", "my questions",
    "my activity", "my history",
    "show me my", "list my",
)


def _is_system_intelligence(query: str) -> bool:
    """True if the query asks about platform usage / audit data, not the
    document corpus. Triggered by phrases like 'recent queries asked by
    users', 'top queries', 'who is asking', 'usage stats'."""
    t = query.strip().lower().rstrip("?.! ")
    if not t:
        return False
    return any(p in t for p in _SYSTEM_INTEL_PHRASES)


def _format_audit_for_llm(rows, scope: str) -> str:
    """Compact, deterministic rendering of audit rows for the LLM context.
    Each row becomes one line of structured fields the model can quote
    accurately. Most-recent first, hard-capped so the prompt stays bounded.
    """
    if not rows:
        return "(no audit rows available for this scope)"
    lines = []
    for r in rows[:30]:
        ts = r.ts.strftime("%Y-%m-%d %H:%M") if hasattr(r.ts, "strftime") else str(r.ts)
        mode = r.answer_mode or "grounded"
        latency = r.latency_total_ms or 0
        faith = (
            f"faith={r.faithfulness:.2f}"
            if r.faithfulness is not None and r.faithfulness >= 0
            else "faith=—"
        )
        cached = "cached" if getattr(r, "cached", False) else "live"
        username = r.username if scope == "all-users" else "you"
        q = (r.query or "").replace("\n", " ").strip()[:160]
        lines.append(
            f"- [{ts}] {username} (L{r.user_level}) → {mode} · {latency}ms · {faith} · {cached}"
            f"\n    query: {q}"
        )
    return "\n".join(lines)


def _is_meta_conversation(query: str, history) -> bool:
    """True if the query asks about THIS chat (its own history) rather
    than the document corpus. Requires history to exist — asking
    'what was my first question' in turn 1 is just a regular question.
    """
    if not history:
        return False
    t = query.strip().lower().rstrip("?.! ")
    if not t:
        return False
    # Short queries that contain a meta cue are very likely meta-questions.
    return any(p in t for p in _META_CONV_PHRASES)


def _is_social(query: str) -> bool:
    """True if the query is a greeting / thanks / meta-question.

    Only triggers on short inputs (<= 8 words) to avoid swallowing substantive
    questions that happen to open with 'hi'. Matches whole-string exact first,
    then whitelisted prefixes.
    """
    t = query.strip().lower().rstrip("!. ")
    if not t:
        return False
    if len(t.split()) > 8:
        return False
    if t in _SOCIAL_EXACT:
        return True
    return any(t.startswith(p.rstrip()) and len(t) <= 40 for p in _SOCIAL_PREFIXES)


_REFUSAL_PHRASES = (
    "could not find",
    "cannot find",
    "can't find",
    "couldn't find",
    "not mentioned",
    "not in the provided",
    "not available in the provided",
    "no information",
    "isn't mentioned",
    "is not mentioned",
    "don't have information",
    "do not have information",
    "not found in the",
)


def _answer_is_refusal(text: str) -> bool:
    """True if a short LLM answer reads like a 'not in the docs' refusal.
    We gate on length to avoid false positives on long, well-cited answers
    that happen to quote a refusal-like phrase inside a larger explanation.
    """
    if not text:
        return False
    t = text.strip().lower()
    if len(t) > 400:
        return False
    return any(p in t for p in _REFUSAL_PHRASES)


def _passes_bar(chunks) -> bool:
    if not chunks:
        return False
    top_rrf = chunks[0].rrf_score or 0.0
    top_rerank = chunks[0].rerank_score or 0.0
    if top_rrf >= STRONG_RRF:
        return True
    if top_rerank >= STRONG_RERANK:
        return True
    if top_rrf >= MEDIUM_RRF and top_rerank >= MEDIUM_RERANK:
        return True
    return False


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def _upgrade_title_bg(thread_id: str, query: str) -> None:
    """Background task: generate a nicer title after the stream has begun."""
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [{"role": "user", "content": TITLE_PROMPT.format(query=query)}],
                max_tokens=40,
                temperature=0.3,
            ),
            timeout=15.0,
        )
        cleaned = (txt or "").strip().strip('"').strip("'").split("\n", 1)[0][:80]
        if cleaned and len(cleaned) > 3:
            # Find the thread's user_id via the thread itself (rename requires user_id).
            from sqlmodel import Session

            from src.core.store import _get_engine

            with Session(_get_engine()) as s:
                t = s.get(models.ChatThread, thread_id)
                if t is not None:
                    models.rename_thread(thread_id, int(t.user_id), cleaned)
    except Exception:
        pass


async def _multi_query(query: str) -> list[str]:
    """Fan-out: one query → 3 LLM rewrites. Graceful fallback to [query]."""
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [{"role": "user", "content": MULTI_QUERY_PROMPT.format(query=query)}],
                max_tokens=180,
                temperature=0.5,
            ),
            timeout=8.0,
        )
        lines = [ln.strip(" -*1234567890.").strip() for ln in txt.splitlines() if ln.strip()]
        # Keep the original + first 2 rewrites.
        rewrites = [q for q in lines if q and q.lower() != query.lower().strip()][:2]
        return [query, *rewrites]
    except Exception:
        return [query]


# Markers that strongly suggest a user message depends on prior chat context.
_FOLLOWUP_WORDS = {
    "it", "its", "they", "them", "their", "that", "this", "those", "these",
    "he", "she", "his", "her", "him", "also", "too",
}
_FOLLOWUP_PHRASES = (
    "tell me more", "more detail", "more details", "in more detail",
    "explain more", "explain in", "elaborate", "go deeper", "dive deeper",
    "and why", "and how", "why is that", "how so", "what about",
    "any more", "any other", "keep going", "continue",
)


def _looks_like_followup(query: str) -> bool:
    """True if the query plausibly references prior conversation context.

    Fires on: short inputs (<=4 words), queries starting with an anaphoric
    pronoun, or queries containing canonical follow-up phrases. This is a
    *necessary* condition for running contextualization — we skip the LLM
    rewrite call on clearly self-contained questions to avoid latency.
    """
    t = query.strip().lower().rstrip("?.! ")
    if not t:
        return False
    words = t.split()
    if len(words) <= 4:
        return True
    first = words[0]
    if first in _FOLLOWUP_WORDS:
        return True
    return any(p in t for p in _FOLLOWUP_PHRASES)


def _budget_history(history, *, max_chars: int, max_turns: int) -> list:
    """Walk history newest-first, accumulating turns until either the char
    budget or turn cap is hit, then return them in chronological order. This
    lets the model remember as far back as possible in a long thread (Q11
    can reference Q3) without ever blowing the prompt budget."""
    picked = []
    used = 0
    for m in reversed(history or []):
        role = getattr(m, "role", None)
        content = (getattr(m, "content", "") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        cost = len(content) + 16  # ~16 chars overhead for role label + newlines
        if used + cost > max_chars and picked:
            break
        picked.append(m)
        used += cost
        if len(picked) >= max_turns:
            break
    picked.reverse()
    return picked


async def _contextualize_query(query: str, history) -> str:
    """Rewrite a follow-up message into a self-contained retrieval query.

    Walks the thread's history within a char budget (so a Q11 that refers
    back to a Q3 topic still sees Q3), and asks the LLM to rewrite the
    latest message as a standalone retrieval query. Falls back to the
    original query on any failure so retrieval still gets a shot.
    """
    if not history:
        return query
    trimmed = _budget_history(history, max_chars=8000, max_turns=30)
    if not trimmed:
        return query
    lines = [
        f"{'User' if getattr(m, 'role', None) == 'user' else 'Assistant'}: "
        f"{(getattr(m, 'content', '') or '').strip()}"
        for m in trimmed
    ]
    hist_text = "\n".join(lines)
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [
                    {
                        "role": "user",
                        "content": CONTEXTUALIZE_PROMPT.format(
                            history=hist_text, query=query
                        ),
                    }
                ],
                max_tokens=120,
                temperature=0.1,
            ),
            timeout=6.0,
        )
        cleaned = (txt or "").strip().strip('"').strip("'").split("\n", 1)[0][:300]
        return cleaned or query
    except Exception:
        return query


async def _corrective_rewrite(query: str) -> str:
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [{"role": "user", "content": CORRECTIVE_PROMPT.format(query=query)}],
                max_tokens=80,
                temperature=0.4,
            ),
            timeout=6.0,
        )
        cleaned = (txt or "").strip().strip('"').split("\n", 1)[0][:300]
        return cleaned or query
    except Exception:
        return query


async def _faithfulness_score(answer: str, chunks) -> float:
    """LLM-judged 0..1 score of how faithful the answer is to the sources."""
    if not chunks or not answer.strip():
        return -1.0
    srcs = "\n\n".join(
        f"[Source {c.source_index}] {c.text[:600]}" for c in chunks[:5]
    )
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [
                    {
                        "role": "user",
                        "content": FAITHFULNESS_PROMPT.format(
                            sources=srcs, answer=answer[:2000]
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
                    return round(v, 3)
            except ValueError:
                continue
    except Exception:
        pass
    return -1.0


def _merge_chunks_rrf(chunk_lists: list[list], k: int = 60):
    """Fuse multiple ranked chunk lists with RRF on (doc_id, chunk_index)."""
    agg: dict[str, dict] = {}
    for chunks in chunk_lists:
        for rank, c in enumerate(chunks, start=1):
            key = f"{c.doc_id}:{c.filename}:{c.page}:{hash(c.text[:80])}"
            agg.setdefault(key, {"chunk": c, "rrf": 0.0, "rerank": c.rerank_score or 0.0})
            agg[key]["rrf"] += 1.0 / (k + rank)
            # keep the max rerank seen across variants
            if c.rerank_score and c.rerank_score > agg[key]["rerank"]:
                agg[key]["rerank"] = c.rerank_score
    items = sorted(agg.values(), key=lambda v: -v["rrf"])
    out = []
    for i, it in enumerate(items[:10], start=1):
        c = it["chunk"]
        c.source_index = i
        c.rrf_score = it["rrf"]
        c.rerank_score = it["rerank"]
        out.append(c)
    return out


async def _retrieve_with_timing(
    query: str,
    user_level: int,
    req: ChatRequest,
    bypass: bool = False,
    caller_role: str | None = None,
):
    t_retrieve = time.perf_counter()
    chunks = await retrieve(
        query=query,
        doc_ids=req.doc_ids or None,
        use_hyde=req.use_hyde,
        use_rerank=req.use_rerank,
        section_filter=req.section_filter,
        top_k=req.top_k,
        max_doc_level=None if bypass else user_level,
        bypass_rbac=bypass,
        caller_role=caller_role,
    )
    retrieve_ms = int((time.perf_counter() - t_retrieve) * 1000)
    return chunks, retrieve_ms


async def _retrieve_multi(
    queries: list[str],
    user_level: int,
    req: ChatRequest,
    caller_role: str | None = None,
):
    """Run retrieval for each query variant in parallel, fuse with RRF."""
    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[_retrieve_with_timing(q, user_level, req, caller_role=caller_role) for q in queries],
        return_exceptions=True,
    )
    chunk_lists = []
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        chunks, _ = r
        chunk_lists.append(chunks)
    if not chunk_lists:
        return [], int((time.perf_counter() - t0) * 1000)
    fused = _merge_chunks_rrf(chunk_lists) if len(chunk_lists) > 1 else chunk_lists[0]
    return fused[: req.top_k], int((time.perf_counter() - t0) * 1000)


async def _stream_grounded(query, chunks, history):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Budget-based history so the model can reference much earlier turns
    # (Q11 → Q3) when the thread gets long, while staying well under the
    # context window once sources + completion room are accounted for.
    for m in _budget_history(history, max_chars=6000, max_turns=20):
        messages.append({"role": m.role, "content": m.content})
    context = build_context_block(chunks)
    messages.append({"role": "user", "content": build_user_prompt(query, context)})
    async for delta in _stream_chat(messages, max_tokens=600, temperature=0.2):
        yield delta


async def _stream_general(query, history):
    messages = [{"role": "system", "content": GENERAL_SYSTEM_PROMPT}]
    for m in _budget_history(history, max_chars=6000, max_turns=20):
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": query})
    async for delta in _stream_chat(messages, max_tokens=600, temperature=0.4):
        yield delta


async def _stream_system_intel(query, user, audit_rows, history):
    """Stream an answer to a system-intelligence question using audit data
    as the context. Caller's role determines the scope: exec sees all
    users; everyone else sees only their own activity.
    """
    scope = "all-users" if user.role == "executive" else f"only your own ({user.username})"
    audit_text = _format_audit_for_llm(audit_rows, scope=scope)
    system_prompt = SYSTEM_INTEL_PROMPT.format(
        scope=scope,
        n_rows=len(audit_rows),
        audit=audit_text,
    )
    messages = [{"role": "system", "content": system_prompt}]
    for m in _budget_history(history, max_chars=3000, max_turns=10):
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": query})
    async for delta in _stream_chat(messages, max_tokens=500, temperature=0.2):
        yield delta


async def _stream_meta(query, history):
    """Stream an answer to a meta-conversation question using only history.
    Never touches retrieval — we send the full (budget-trimmed) chat log
    and ask the LLM to answer from it. Uses a generous history budget
    because a meta-question like 'what was my first question' literally
    needs access to the earliest turns."""
    messages = [{"role": "system", "content": META_CONVERSATION_PROMPT}]
    for m in _budget_history(history, max_chars=8000, max_turns=40):
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": query})
    async for delta in _stream_chat(messages, max_tokens=500, temperature=0.3):
        yield delta


@router.post("/chat")
async def chat(req: ChatRequest, user: CurrentUser = Depends(chat_rate_limit)):
    async def event_generator():
        t_total = time.perf_counter()

        # ── 1. Thread setup ───────────────────────────────────────────────
        is_new_thread = False
        thread_id = req.thread_id
        title = ""
        if thread_id:
            thread = models.get_thread(thread_id, user.id)
            if thread is None:
                yield {"event": "error", "data": json.dumps({"message": "thread not found"})}
                return
            title = thread.title
            # Thread was pre-created via POST /api/threads (generic "New chat" title)
            # and this is the first real turn — upgrade the title from the query.
            if title in ("", "New chat"):
                fallback = " ".join(req.query.split()[:6])[:80] or "New chat"
                if fallback != "New chat":
                    models.rename_thread(thread_id, user.id, fallback)
                    title = fallback
                is_new_thread = True
                asyncio.create_task(_upgrade_title_bg(thread_id, req.query))
        else:
            # Fast path: seed with 6-word fallback title immediately,
            # upgrade to LLM-generated title in the background.
            title = " ".join(req.query.split()[:6])[:80] or "New chat"
            thread = models.create_thread(user.id, title=title)
            thread_id = thread.id
            is_new_thread = True
            asyncio.create_task(_upgrade_title_bg(thread_id, req.query))

        yield {
            "event": "thread",
            "data": json.dumps({"thread_id": thread_id, "title": title, "is_new": is_new_thread}),
        }

        # ── 1b. Social short-circuit ─────────────────────────────────────
        # Greetings / thanks / meta-questions ("what can you do?") never hit
        # retrieval — we return a role-aware welcome instantly so the agent
        # feels hospitable, and no cold "no confident answer" card is shown.
        if _is_social(req.query):
            payload = build_welcome_payload(user)
            greeting = payload["greeting"]
            yield {
                "event": "welcome",
                "data": json.dumps(payload),
            }
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "ok": True,
                        "answer_mode": "social",
                        "thread_id": thread_id,
                        "cached": False,
                        "latency_ms": {
                            "retrieve": 0,
                            "rerank": 0,
                            "generate": 0,
                            "total": int((time.perf_counter() - t_total) * 1000),
                        },
                        "tokens": {"prompt": 0, "completion": 0},
                        "corrective_retries": 0,
                        "faithfulness": -1.0,
                    }
                ),
            }
            # Persist the turn + audit row so thread history stays coherent.
            try:
                models.append_turn(thread_id=thread_id, role="user", content=req.query)
                models.append_turn(
                    thread_id=thread_id,
                    role="assistant",
                    content=greeting,
                    sources_json="",
                    refused=False,
                    answer_mode="social",
                )
                models.touch_thread(thread_id)
                models.write_audit(
                    models.AuditLog(
                        user_id=user.id,
                        username=user.username,
                        user_level=user.level,
                        query=req.query,
                        refused=False,
                        returned_chunks=0,
                        allowed_doc_ids="",
                        answer_mode="social",
                        latency_retrieve_ms=0,
                        latency_rerank_ms=0,
                        latency_generate_ms=0,
                        latency_total_ms=int((time.perf_counter() - t_total) * 1000),
                        tokens_prompt=0,
                        tokens_completion=0,
                        cached=False,
                        corrective_retries=0,
                        faithfulness=-1.0,
                    )
                )
            except Exception:
                pass
            return

        # ── 1bb. System-intelligence short-circuit ────────────────────────
        # "Recent queries by users" / "top users" / "audit" — answer from
        # audit data, not the doc corpus. Exec sees all users; everyone
        # else sees only their own activity (RBAC at the data layer).
        if _is_system_intelligence(req.query):
            from sqlmodel import Session, desc, select as _select
            from src.core.store import _get_engine as _store_engine

            with Session(_store_engine()) as s:
                q = _select(models.AuditLog).order_by(desc(models.AuditLog.ts))
                if user.role != "executive":
                    q = q.where(models.AuditLog.user_id == user.id)
                audit_rows = list(s.exec(q.limit(30)))

            yield {
                "event": "general_mode",
                "data": json.dumps(
                    {"message": "Answering from audit data (system intelligence)."}
                ),
            }
            t_gen = time.perf_counter()
            full_answer = ""
            async for delta in _stream_system_intel(req.query, user, audit_rows, req.history):
                full_answer += delta
                yield {"event": "token", "data": json.dumps({"delta": delta})}
            generate_ms = int((time.perf_counter() - t_gen) * 1000)
            answer_mode = "system"
            tokens_prompt = _approx_tokens(SYSTEM_INTEL_PROMPT + req.query)
            tokens_completion = _approx_tokens(full_answer)
            try:
                models.append_turn(thread_id=thread_id, role="user", content=req.query)
                models.append_turn(
                    thread_id=thread_id,
                    role="assistant",
                    content=full_answer or "",
                    sources_json="",
                    refused=False,
                    answer_mode="system",
                )
                models.touch_thread(thread_id)
                models.write_audit(
                    models.AuditLog(
                        user_id=user.id,
                        username=user.username,
                        user_level=user.level,
                        query=req.query,
                        refused=False,
                        returned_chunks=0,
                        allowed_doc_ids="",
                        answer_mode="system",
                        latency_retrieve_ms=0,
                        latency_rerank_ms=0,
                        latency_generate_ms=generate_ms,
                        latency_total_ms=int((time.perf_counter() - t_total) * 1000),
                        tokens_prompt=tokens_prompt,
                        tokens_completion=tokens_completion,
                        cached=False,
                        corrective_retries=0,
                        faithfulness=-1.0,
                    )
                )
            except Exception:
                pass
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "ok": True,
                        "answer_mode": "system",
                        "thread_id": thread_id,
                        "cached": False,
                        "latency_ms": {
                            "retrieve": 0,
                            "rerank": 0,
                            "generate": generate_ms,
                            "total": int((time.perf_counter() - t_total) * 1000),
                        },
                        "tokens": {"prompt": tokens_prompt, "completion": tokens_completion},
                        "corrective_retries": 0,
                        "faithfulness": -1.0,
                    }
                ),
            }
            return

        # ── 1c. Meta-conversation short-circuit ───────────────────────────
        # "What was my first question?" / "summarize our chat" are about
        # THIS conversation, not the corpus. Route straight to generation
        # using the chat history — don't waste retrieval on the doc store
        # (it finds nothing relevant and the flow collapses to "no
        # confident answer").
        if _is_meta_conversation(req.query, req.history):
            yield {
                "event": "general_mode",
                "data": json.dumps(
                    {"message": "Answering from this chat's history."}
                ),
            }
            t_gen = time.perf_counter()
            full_answer = ""
            async for delta in _stream_meta(req.query, req.history):
                full_answer += delta
                yield {"event": "token", "data": json.dumps({"delta": delta})}
            generate_ms = int((time.perf_counter() - t_gen) * 1000)
            answer_mode = "meta"
            tokens_prompt = _approx_tokens(
                META_CONVERSATION_PROMPT + req.query + " ".join(
                    (m.content or "") for m in (req.history or [])
                )
            )
            tokens_completion = _approx_tokens(full_answer)
            try:
                models.append_turn(thread_id=thread_id, role="user", content=req.query)
                models.append_turn(
                    thread_id=thread_id,
                    role="assistant",
                    content=full_answer or "",
                    sources_json="",
                    refused=False,
                    answer_mode="meta",
                )
                models.touch_thread(thread_id)
                models.write_audit(
                    models.AuditLog(
                        user_id=user.id,
                        username=user.username,
                        user_level=user.level,
                        query=req.query,
                        refused=False,
                        returned_chunks=0,
                        allowed_doc_ids="",
                        answer_mode="meta",
                        latency_retrieve_ms=0,
                        latency_rerank_ms=0,
                        latency_generate_ms=generate_ms,
                        latency_total_ms=int((time.perf_counter() - t_total) * 1000),
                        tokens_prompt=tokens_prompt,
                        tokens_completion=tokens_completion,
                        cached=False,
                        corrective_retries=0,
                        faithfulness=-1.0,
                    )
                )
            except Exception:
                pass
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "ok": True,
                        "answer_mode": "meta",
                        "thread_id": thread_id,
                        "cached": False,
                        "latency_ms": {
                            "retrieve": 0,
                            "rerank": 0,
                            "generate": generate_ms,
                            "total": int((time.perf_counter() - t_total) * 1000),
                        },
                        "tokens": {"prompt": tokens_prompt, "completion": tokens_completion},
                        "corrective_retries": 0,
                        "faithfulness": -1.0,
                    }
                ),
            }
            return

        # ── 2. Cache lookup ──────────────────────────────────────────────
        cache_settings = {
            "hyde": req.use_hyde,
            "rerank": req.use_rerank,
            "k": req.top_k,
            "sections": req.section_filter or [],
        }
        cached = chat_cache.get(user.id, user.level, req.query, req.doc_ids or [], cache_settings)

        # ── State we'll fill in ──────────────────────────────────────────
        answer_mode = "grounded"
        full_answer = ""
        cited_doc_ids: list[str] = []
        returned_chunks = 0
        sources_json = ""
        retrieve_ms = 0
        rerank_ms = 0
        generate_ms = 0
        corrective_retries = 0
        is_cached = False
        faithfulness = -1.0
        tokens_prompt = 0
        tokens_completion = 0

        try:
            if cached is not None:
                # Replay cached response quickly — still audited as cached=True.
                is_cached = True
                answer_mode = cached["answer_mode"]
                full_answer = cached["answer"]
                returned_chunks = cached["returned_chunks"]
                cited_doc_ids = cached["cited_doc_ids"]
                sources_json = cached["sources_json"]
                faithfulness = cached.get("faithfulness", -1.0)
                tokens_prompt = cached.get("tokens_prompt", 0)
                tokens_completion = cached.get("tokens_completion", 0)

                yield {"event": "cached", "data": json.dumps({"hit": True})}

                if answer_mode == "grounded":
                    yield {
                        "event": "sources",
                        "data": json.dumps({"sources": json.loads(sources_json)}),
                    }
                    # Replay answer as one chunk (skip token-level streaming)
                    yield {"event": "token", "data": json.dumps({"delta": full_answer})}
                elif answer_mode == "general":
                    yield {
                        "event": "general_mode",
                        "data": json.dumps({"message": "Cached general-knowledge answer."}),
                    }
                    yield {"event": "token", "data": json.dumps({"delta": full_answer})}
                elif answer_mode == "refused":
                    yield {"event": "refused", "data": json.dumps({"message": full_answer})}
                else:
                    yield {"event": "unknown", "data": json.dumps({"message": full_answer})}

            else:
                # ── 2b. Conversational contextualization ──────────────────
                # If the user's message is a follow-up ("tell me more",
                # "why?", pronoun-leading, etc.) and we have history, ask an
                # LLM to rewrite it into a self-contained question so the
                # retriever has something concrete to match against. Without
                # this step, "tell me in more detail" retrieves nothing and
                # the answer collapses to "no confident answer".
                search_query = req.query
                if req.history and _looks_like_followup(req.query):
                    rewritten = await _contextualize_query(req.query, req.history)
                    if rewritten and rewritten.strip().lower() != req.query.strip().lower():
                        search_query = rewritten
                        yield {
                            "event": "contextualized",
                            "data": json.dumps(
                                {"rewritten": search_query, "original": req.query}
                            ),
                        }

                # ── 3. Multi-query retrieval (parallel fan-out, opt-in) ───
                if req.use_multi_query:
                    queries = await _multi_query(search_query)
                else:
                    queries = [search_query]
                chunks, retrieve_ms = await _retrieve_multi(
                    queries, user.level, req, caller_role=user.role
                )

                # Rerank already done inside retrieve; we expose the split only
                # for observability. Approximation: generate_ms and rerank_ms
                # are not cleanly separable under the current pipeline, so we
                # attribute ~40% of retrieve_ms to rerank as a sensible split.
                rerank_ms = int(retrieve_ms * 0.4)

                # ── 4. Relevance gate ─────────────────────────────────────
                grounded_ok = bool(chunks) and _passes_bar(chunks)

                # ── 5. Corrective RAG — one retry if first pass weak ─────
                # Only fire for substantive queries (≥2 content words) — avoids
                # wasting a rewrite LLM call on "hello", "hi", etc.
                if req.use_corrective and not grounded_ok and _is_substantive_query(req.query):
                    rewritten = await _corrective_rewrite(req.query)
                    if rewritten and rewritten.strip().lower() != req.query.strip().lower():
                        corrective_retries = 1
                        t_r = time.perf_counter()
                        retry_chunks, _ = await _retrieve_with_timing(
                            rewritten, user.level, req, caller_role=user.role
                        )
                        retrieve_ms += int((time.perf_counter() - t_r) * 1000)
                        if retry_chunks and _passes_bar(retry_chunks):
                            chunks = retry_chunks
                            grounded_ok = True
                            yield {
                                "event": "corrective",
                                "data": json.dumps(
                                    {"rewritten": rewritten, "original": req.query}
                                ),
                            }

                # ── 6. Decide final mode ─────────────────────────────────
                if grounded_ok:
                    answer_mode = "grounded"
                elif not _looks_like_real_query(req.query):
                    answer_mode = "unknown"
                else:
                    probe, probe_ms = await _retrieve_with_timing(
                        req.query, user.level, req, bypass=True
                    )
                    retrieve_ms += probe_ms
                    has_higher_match = bool(probe) and _passes_bar(probe)
                    if user.level >= 4:
                        answer_mode = "refused" if has_higher_match else "general"
                    else:
                        answer_mode = "unknown"

                # ── 7. Emit + stream ─────────────────────────────────────
                t_gen = time.perf_counter()
                if answer_mode == "grounded":
                    returned_chunks = len(chunks)
                    cited_doc_ids = sorted({c.doc_id for c in chunks if c.doc_id})
                    sources_payload = [
                        {
                            "index": c.source_index,
                            "doc_id": c.doc_id,
                            "filename": c.filename,
                            "page": c.page,
                            "section": c.section,
                            "text": c.text,
                            "rrf_score": c.rrf_score,
                            "rerank_score": c.rerank_score,
                            "chunk_index": c.chunk_index,
                        }
                        for c in chunks
                    ]
                    sources_json = json.dumps(sources_payload)
                    yield {"event": "sources", "data": json.dumps({"sources": sources_payload})}
                    async for delta in _stream_grounded(req.query, chunks, req.history):
                        full_answer += delta
                        yield {"event": "token", "data": json.dumps({"delta": delta})}

                elif answer_mode == "general":
                    yield {
                        "event": "general_mode",
                        "data": json.dumps(
                            {"message": "Not found in the corpus — general knowledge."}
                        ),
                    }
                    async for delta in _stream_general(req.query, req.history):
                        full_answer += delta
                        yield {"event": "token", "data": json.dumps({"delta": delta})}

                elif answer_mode == "refused":
                    msg = (
                        "A document matching this query exists above your clearance. "
                        "This diagnostic is shown to executives for auditability."
                    )
                    full_answer = msg
                    yield {"event": "refused", "data": json.dumps({"message": msg})}

                else:  # unknown
                    msg = (
                        "I don't have a confident answer for that question. Try "
                        "rephrasing, or check the Knowledge base tab for what's available."
                    )
                    full_answer = msg
                    yield {"event": "unknown", "data": json.dumps({"message": msg})}

                generate_ms = int((time.perf_counter() - t_gen) * 1000)

                # Token estimates
                tokens_prompt = _approx_tokens(
                    SYSTEM_PROMPT + req.query + (sources_json or "")
                )
                tokens_completion = _approx_tokens(full_answer)

                # ── 8. Faithfulness (grounded only, skippable via flag) ──
                if req.use_faithfulness and answer_mode == "grounded" and full_answer.strip():
                    faithfulness = await _faithfulness_score(full_answer, chunks)

                # ── 8b. Post-hoc demotion: grounded → unknown when the LLM
                # itself refused. The LLM's refusal is the authoritative
                # signal — it has seen the chunks and decided they don't
                # answer the question. Faithfulness is a corroborator, not a
                # gate: a vacuous refusal can still score 100% faithful
                # (trivially consistent with thin sources), and a low score
                # can just mean the judge was noisy. If the LLM's own answer
                # reads like "I could not find this" — short, explicit,
                # non-substantive — we trust it over the retrieval scores,
                # drop the sources, and render the "No confident answer"
                # card. We keep `full_answer` so the UI shows the LLM's
                # wording rather than a generic template.
                if answer_mode == "grounded" and _answer_is_refusal(full_answer):
                    answer_mode = "unknown"
                    returned_chunks = 0
                    cited_doc_ids = []
                    sources_json = ""

                # ── 9. Cache it ──────────────────────────────────────────
                chat_cache.put(
                    user.id,
                    user.level,
                    req.query,
                    req.doc_ids or [],
                    cache_settings,
                    {
                        "answer_mode": answer_mode,
                        "answer": full_answer,
                        "returned_chunks": returned_chunks,
                        "cited_doc_ids": cited_doc_ids,
                        "sources_json": sources_json,
                        "faithfulness": faithfulness,
                        "tokens_prompt": tokens_prompt,
                        "tokens_completion": tokens_completion,
                    },
                )

        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            yield {"event": "error", "data": json.dumps({"message": err})}
            full_answer = f"⚠️ {err}"
            answer_mode = "unknown"

        finally:
            latency_total_ms = int((time.perf_counter() - t_total) * 1000)
            try:
                models.append_turn(
                    thread_id=thread_id,
                    role="user",
                    content=req.query,
                )
                models.append_turn(
                    thread_id=thread_id,
                    role="assistant",
                    content=full_answer or "",
                    sources_json=sources_json,
                    refused=(answer_mode in {"refused", "unknown"}),
                    answer_mode=answer_mode,
                    faithfulness=faithfulness,
                )
                models.touch_thread(thread_id)
                models.write_audit(
                    models.AuditLog(
                        user_id=user.id,
                        username=user.username,
                        user_level=user.level,
                        query=req.query,
                        refused=(answer_mode in {"refused", "unknown"}),
                        returned_chunks=returned_chunks,
                        allowed_doc_ids=",".join(cited_doc_ids),
                        answer_mode=answer_mode,
                        latency_retrieve_ms=retrieve_ms,
                        latency_rerank_ms=rerank_ms,
                        latency_generate_ms=generate_ms,
                        latency_total_ms=latency_total_ms,
                        tokens_prompt=tokens_prompt,
                        tokens_completion=tokens_completion,
                        cached=is_cached,
                        corrective_retries=corrective_retries,
                        faithfulness=faithfulness,
                    )
                )
            except Exception:
                pass

        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "ok": True,
                    "answer_mode": answer_mode,
                    "thread_id": thread_id,
                    "cached": is_cached,
                    "latency_ms": {
                        "retrieve": retrieve_ms,
                        "rerank": rerank_ms,
                        "generate": generate_ms,
                        "total": int((time.perf_counter() - t_total) * 1000),
                    },
                    "tokens": {"prompt": tokens_prompt, "completion": tokens_completion},
                    "corrective_retries": corrective_retries,
                    "faithfulness": faithfulness,
                }
            ),
        }

    return EventSourceResponse(event_generator())
