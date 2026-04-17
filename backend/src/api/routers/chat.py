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
import re
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.api.routers.welcome import build_welcome_payload
from src.auth.dependencies import CurrentUser
from src.core import chat_cache, models
from src.core.prompts import (
    CONTEXTUALIZE_PROMPT,
    CORRECTIVE_PROMPT,
    FAITHFULNESS_PROMPT,
    GENERAL_SYSTEM_PROMPT,
    INTENT_CLASSIFY_PROMPT,
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
    # Pronouns + anaphora
    "it", "its", "they", "them", "their", "that", "this", "those", "these",
    "he", "she", "his", "her", "him", "also", "too",
    # Elaboration/format-request verbs (2026-04-16, follow-up bug fix):
    # "give N points", "list ...", "show the ...", "describe ...",
    # "explain ...", "format as ...", "summarize", "break down", etc. are
    # follow-ups in intent even when they don't start with a pronoun.
    "give", "show", "list", "explain", "describe", "summarize", "summarise",
    "expand", "format", "structure", "organize", "organise", "outline",
    "rephrase", "rewrite", "reformat", "bullet", "bulletize", "break",
    "simplify", "clarify",
}
_FOLLOWUP_PHRASES = (
    "tell me more", "more detail", "more details", "in more detail",
    "explain more", "explain in", "elaborate", "go deeper", "dive deeper",
    "and why", "and how", "why is that", "how so", "what about",
    "any more", "any other", "keep going", "continue",
    # Format/structure asks (added 2026-04-16 follow-up-context fix).
    # These never mention the topic directly — they depend on history for
    # meaning. Without matching here, contextualize never fires and
    # retrieval misses because "structured manner" isn't a topic keyword.
    "structured", "structure it", "in a structured", "in points",
    "as bullets", "in bullet", "bullet points", "as a list", "in a list",
    "briefly", "in short", "in summary", "short version", "long version",
    "with more detail", "more details", "in detail",
    "points", " format", "format as", "format it",
    "break down", "break it down", "step by step", "step-by-step",
    "condense", "expand on", "same question",
)


def _looks_like_followup(query: str) -> bool:
    """True if the query plausibly references prior conversation context.

    Fires on: short inputs (<=4 words), queries starting with an anaphoric
    pronoun OR elaboration/format verb, queries containing canonical
    follow-up phrases, or any query <= 10 words that doesn't obviously
    introduce a new topic (no proper noun-looking tokens). This is a
    *necessary* condition for running contextualization — we skip the LLM
    rewrite call on clearly self-contained questions to avoid latency.

    The 10-word rule catches cases like "answer with more details and
    structured manner" (7 words, topic-free) that were previously
    falling through to retrieval with no keywords to match.
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
    if any(p in t for p in _FOLLOWUP_PHRASES):
        return True
    # Heuristic: short queries with no capitalised words in the ORIGINAL
    # (pre-lowercase) input probably don't name a new topic, so they're
    # leaning on conversation context. We check the original casing by
    # looking at the caller's input before we lowercased it.
    if len(words) <= 10:
        original_tokens = query.strip().rstrip("?.!").split()
        # If NO token except the first word starts with a capital letter,
        # the query is almost certainly topic-less.
        has_proper_noun = any(
            tok[:1].isupper() for tok in original_tokens[1:]
        )
        if not has_proper_noun:
            return True
    return False


# ─── Compound-question detection (Tier 1 follow-up: recall improvement) ─
# Sumith's evaluation (2026-04-16): faithfulness is perfect (zero
# hallucinations, every cited fact accurate) — but compound questions
# with 5 sub-parts can't fit in top_k=5 chunks, so half the sub-
# questions return "context does not provide" even though the answer
# IS in the corpus. Fix: detect compound queries and auto-expand
# top_k for retrieval. Simple questions stay at the base (fast, cheap).
_COMPOUND_CONJUNCTIONS = (
    " and ", " plus ", " as well as ", " along with ", " together with ",
    "; ", ", and ", ", or ", " or ",
)
_ENUMERATION_PATTERNS = (
    re.compile(
        r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
        r"(?:things|points|items|reasons|steps|aspects|components|"
        r"factors|parts|questions|sub[- ]?questions|areas|bullets)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:list|enumerate|break\s+down|decompose)\b", re.IGNORECASE),
)
_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _estimate_subquestions(query: str) -> int:
    """Rough count of sub-questions packed into one user turn.

    Heuristics (stacked — compound asks can score high):
      - Each question-word beyond the first (what/how/why/when/where/who)
      - Each conjunction separating topics (" and ", ", or ", etc.)
      - Enumeration cues ("five points", "list the N things"): counts
        the stated N directly.
      - Long queries (>25 words, >45 words): +1, +2.

    Plain "What is X?" → 1. Long multi-clause compound → 4-6+.
    """
    if not query or not query.strip():
        return 1
    q = query.lower()
    count = 1

    qwords = re.findall(
        r"\b(what|how|why|when|where|who|which|whose|whom)\b", q
    )
    count += max(0, len(qwords) - 1)

    for sep in _COMPOUND_CONJUNCTIONS:
        count += q.count(sep)

    # Colon-then-enumeration pattern: "tell me X: a, b, c, d" — every
    # comma after a colon is a distinct sub-part. Cap the contribution
    # at 6 to avoid exploding on natural comma-rich prose.
    colon_idx = q.find(":")
    if colon_idx >= 0 and colon_idx < len(q) - 1:
        tail = q[colon_idx + 1:]
        commas = tail.count(",")
        if commas >= 1:
            count += min(6, commas)

    for pat in _ENUMERATION_PATTERNS:
        m = pat.search(q)
        if not m:
            continue
        groups = m.groups() if m.groups() else ()
        n_token = (groups[0] if groups and groups[0] else "").lower()
        n: int | None = None
        if n_token and n_token.isdigit():
            try:
                n = int(n_token)
            except ValueError:
                n = None
        if n is None:
            n = _NUMBER_WORDS.get(n_token, 3)
        count += max(2, n - 1)

    word_count = len(q.split())
    if word_count > 25:
        count += 1
    if word_count > 45:
        count += 2

    return max(1, count)


def _expanded_top_k(base_top_k: int, sub_questions: int) -> int:
    """Auto-expand top_k for compound questions. Each additional sub-
    question adds ~2 chunks of headroom so the LLM has enough context
    per sub-part. Capped at 12 to bound latency + prompt tokens.

    base=5, sub=1 → 5   (simple question — no change)
    base=5, sub=3 → 9
    base=5, sub=5 → 12  (capped)
    """
    if sub_questions <= 1:
        return base_top_k
    bumped = base_top_k + (sub_questions - 1) * 2
    return min(12, max(base_top_k, bumped))



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


async def _classify_intent(query: str) -> str:
    """Return a one-sentence restatement of the user's query, prefixed with
    "You're asking...". Runs a fast, low-temperature LLM call with a
    short timeout — the user sees this as a reassuring "Understood as"
    pill above the streamed answer. Falls back to the original query on
    timeout or error (we never block the real answer on this).
    """
    try:
        txt = await asyncio.wait_for(
            _complete_chat(
                [{"role": "user", "content": INTENT_CLASSIFY_PROMPT.format(query=query)}],
                max_tokens=60,
                temperature=0.1,
            ),
            timeout=4.0,
        )
        cleaned = (txt or "").strip().strip('"').strip("'").split("\n", 1)[0][:240]
        # Reject the model's noise if it literally echoed the prompt back,
        # or if it answered the question (rare but possible).
        if len(cleaned) < 6 or cleaned.lower().startswith("restatement"):
            return ""
        return cleaned
    except Exception:
        return ""


def _compute_confidence(
    answer_mode: str,
    chunks,
    faithfulness: float,
) -> int | None:
    """Composite 0..100 confidence score exposed to the user as a chip.
    Two signals:
      - top_rerank: how well the best chunk matches the query (retrieval)
      - faithfulness: how grounded the answer is in the sources (judge)

    Grounded: weighted blend (50/50) when both are present, else the
    single signal that is. Clamped to [5, 100] — anything below 5 reads
    as a bug, not a score.
    Non-grounded: returns None (no confidence chip shown).
    """
    if answer_mode != "grounded" or not chunks:
        return None
    top = chunks[0].rerank_score if chunks and chunks[0].rerank_score is not None else None
    if top is None:
        top = chunks[0].rrf_score or 0.0
    # Normalise rerank_score (cross-encoder, can go negative on bad matches
    # for bge-reranker-base — but STRONG hits are ~0.3..0.9). We clamp
    # to [0, 1] for the chip. RRF scores tend to be ~0.01..0.05, so we
    # scale those separately when used as the only signal.
    if top > 1.0:  # unlikely, but keep it safe
        top = 1.0
    if top < 0.0:
        top = 0.0
    # If we're using RRF (no rerank), scale to [0,1] by assuming 0.05 ≈ great.
    if chunks[0].rerank_score is None:
        top = min(1.0, top / 0.05)

    if faithfulness >= 0:
        blended = top * 0.5 + faithfulness * 0.5
    else:
        blended = top  # retrieval-only
    return max(5, min(100, int(round(blended * 100))))


_CITATION_PATTERN = re.compile(r"\[Source\s+(\d+)\]", re.IGNORECASE)


def _verify_citations(answer: str, chunks) -> dict:
    """Verify every [Source N] tag in the answer points to a real chunk
    AND that the surrounding sentence has at least one substantive word
    overlap with that chunk's text.

    Returns:
      {
        "total": int,                 # how many [Source N] tags appeared
        "valid": int,                 # how many resolved to a real chunk
        "fabricated": list[int],      # source numbers cited but not in chunks
        "weak": list[int],            # cited but no meaningful word overlap
        "score": float,               # valid / max(total, 1)
      }

    This catches two failure modes:
      1. The LLM cites [Source 7] when only sources 1-5 exist.
      2. The LLM cites [Source 3] but the sentence has no overlap with
         chunk 3's actual text — usually means the model picked the
         citation arbitrarily after generating the claim.
    """
    if not answer.strip():
        return {"total": 0, "valid": 0, "fabricated": [], "weak": [], "score": 1.0}

    # Build a quick index from source_index → chunk text (lowercased).
    chunk_text_by_idx: dict[int, str] = {}
    for c in chunks:
        if c.source_index and c.text:
            chunk_text_by_idx[c.source_index] = c.text.lower()

    # For each citation, check the surrounding sentence's overlap with
    # the cited chunk's text. We split on sentence-ish boundaries and
    # find the sentence containing the citation tag.
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    fabricated: list[int] = []
    weak: list[int] = []
    valid = 0
    total = 0

    seen_per_sentence: list[tuple[str, set[int]]] = []
    for s in sentences:
        cites = {int(m.group(1)) for m in _CITATION_PATTERN.finditer(s)}
        if cites:
            seen_per_sentence.append((s, cites))

    # Common stopwords — we ignore these when checking overlap so a
    # one-word match like "the" doesn't count.
    _STOP = {
        "the", "a", "an", "is", "are", "was", "were", "of", "to", "in",
        "for", "on", "and", "or", "but", "with", "by", "from", "as",
        "this", "that", "these", "those", "it", "its", "be", "have",
        "has", "had", "do", "does", "did", "will", "would", "should",
        "can", "could", "may", "might", "must", "not", "no", "yes",
        "you", "your", "we", "our", "they", "their", "he", "she",
        "his", "her", "me", "my", "i",
    }

    for sentence, citations_in_sentence in seen_per_sentence:
        sentence_words = {
            w for w in re.findall(r"[a-z0-9]+", sentence.lower())
            if w not in _STOP and len(w) >= 3
        }
        for src_num in citations_in_sentence:
            total += 1
            chunk_text = chunk_text_by_idx.get(src_num)
            if chunk_text is None:
                fabricated.append(src_num)
                continue
            chunk_words = {
                w for w in re.findall(r"[a-z0-9]+", chunk_text)
                if w not in _STOP and len(w) >= 3
            }
            overlap = sentence_words & chunk_words
            if len(overlap) < 2:  # need ≥2 substantive words shared
                weak.append(src_num)
            else:
                valid += 1

    return {
        "total": total,
        "valid": valid,
        "fabricated": sorted(set(fabricated)),
        "weak": sorted(set(weak)),
        "score": round(valid / max(total, 1), 3),
    }


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
    prefer_recent: bool = False,
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
        prefer_recent=prefer_recent,
    )
    retrieve_ms = int((time.perf_counter() - t_retrieve) * 1000)
    return chunks, retrieve_ms


async def _retrieve_multi(
    queries: list[str],
    user_level: int,
    req: ChatRequest,
    caller_role: str | None = None,
    prefer_recent: bool = False,
):
    """Run retrieval for each query variant in parallel, fuse with RRF."""
    t0 = time.perf_counter()
    results = await asyncio.gather(
        *[
            _retrieve_with_timing(
                q, user_level, req, caller_role=caller_role, prefer_recent=prefer_recent
            )
            for q in queries
        ],
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


async def _run_comparison(
    query: str, doc_ids: list[str], user, base_req: ChatRequest
) -> list[dict]:
    """Tier 2.2 — run retrieval + generation ONCE per doc, scoped to that
    single doc, in parallel. Returns one entry per doc:

      {
        "doc_id": "abc",
        "filename": "HR_Policy.docx",
        "label": "HR Policy",
        "answer": "Streamed answer text citing [Source 1] etc.",
        "sources": [<source payload>, ...],
        "ok": True|False,
        "error": "" | "<reason>"
      }

    Non-blocking per doc — if one doc's generation fails, the others still
    come back. Each doc uses its OWN isolated ChatRequest copy so
    top-level fields (doc_ids, preferred_doc_id) don't cross-contaminate.
    """

    async def _one(doc_id: str) -> dict:
        # Scope this sub-request to a single doc. Copy the settings so
        # the outer request's doc_ids / preferred_doc_id don't leak.
        sub_req = ChatRequest(
            query=query,
            doc_ids=[doc_id],
            use_hyde=base_req.use_hyde,
            use_rerank=base_req.use_rerank,
            use_multi_query=False,  # single-doc, no need
            use_corrective=base_req.use_corrective,
            use_faithfulness=False,  # skip to keep comparison fast
            section_filter=base_req.section_filter,
            history=[],
            top_k=base_req.top_k,
            thread_id=None,
            preferred_doc_id=None,
            skip_disambiguation=True,
        )
        try:
            chunks, _ = await _retrieve_with_timing(
                query, user.level, sub_req, caller_role=user.role
            )
        except Exception as e:
            return {
                "doc_id": doc_id,
                "filename": "",
                "label": "",
                "answer": "",
                "sources": [],
                "ok": False,
                "error": f"retrieve: {type(e).__name__}",
            }
        filename = chunks[0].filename if chunks else ""
        if not chunks or not _passes_bar(chunks):
            return {
                "doc_id": doc_id,
                "filename": filename,
                "label": _prettify_filename(filename),
                "answer": "This document doesn't have a strong match for your question.",
                "sources": [],
                "ok": False,
                "error": "weak_match",
            }
        # Generate — collect full answer, no streaming (UX would be chaos
        # with N parallel streams).
        full = ""
        try:
            async for delta in _stream_grounded(query, chunks, []):
                full += delta
        except Exception as e:
            return {
                "doc_id": doc_id,
                "filename": filename,
                "label": _prettify_filename(filename),
                "answer": "",
                "sources": [],
                "ok": False,
                "error": f"generate: {type(e).__name__}",
            }
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
        return {
            "doc_id": doc_id,
            "filename": filename,
            "label": _prettify_filename(filename),
            "answer": full,
            "sources": sources_payload,
            "ok": True,
            "error": "",
        }

    results = await asyncio.gather(*(_one(d) for d in doc_ids))
    return list(results)


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


# ─── Agent: doc-ambiguity detector ──────────────────────────────────────────
# When a user's query legitimately spans multiple distinct documents (two
# policies covering different parties, a technical report and a handbook,
# etc.), blending their chunks into one answer is a correctness bug.
# Instead we pause, return the candidate docs, and let the user pick.

_DISAMBIG_SCORE_GAP = 0.20   # top-2 doc rerank scores within 20% → ambiguous
_DISAMBIG_MIN_DOCS = 2       # need at least 2 distinct docs in top-K
_DISAMBIG_MIN_TOP_SCORE = 0.25  # don't trigger on weak retrievals; grounded
                                 # threshold (STRONG_RERANK=0.30) is the
                                 # anchor, 0.25 leaves room for medium-conf
                                 # cases where disambiguation still helps.


def _prettify_filename(fn: str) -> str:
    """Strip extension + dedupe repeated prefix tokens ('HRMS-HRMS-...' →
    'HRMS-...') + collapse separators to spaces. Used for user-facing
    labels in the disambiguation card."""
    s = fn.rsplit(".", 1)[0] if "." in fn else fn
    parts = [p for p in s.replace("_", "-").split("-") if p]
    deduped: list[str] = []
    for p in parts:
        if not deduped or deduped[-1].lower() != p.lower():
            deduped.append(p)
    return " ".join(deduped).strip() or fn


def _detect_doc_ambiguity(chunks) -> list[dict] | None:
    """Return candidate docs if the top-K reranked chunks span 2+ distinct
    docs with comparable scores, else None.

    Detection rule:
      1. Group chunks by doc_id, keeping max(rerank_score) per doc
      2. Need >=2 distinct docs with the top doc's score >= threshold
      3. The top-2 doc scores must be within _DISAMBIG_SCORE_GAP (20%)
         — otherwise the top doc is clearly winning and we just answer.

    Each candidate is returned with a 1-line hint (first 160 chars of the
    best chunk text from that doc) so the user sees *why* each doc is a
    candidate, not just its filename.
    """
    if not chunks or len(chunks) < 2:
        return None

    by_doc: dict[str, dict] = {}
    for c in chunks:
        if not c.doc_id:
            continue
        score = c.rerank_score if c.rerank_score is not None else c.rrf_score
        entry = by_doc.setdefault(
            c.doc_id,
            {
                "doc_id": c.doc_id,
                "filename": c.filename,
                "top_score": -1.0,
                "top_chunk_text": "",
                "chunk_count": 0,
            },
        )
        entry["chunk_count"] += 1
        if score is not None and score > entry["top_score"]:
            entry["top_score"] = float(score)
            entry["top_chunk_text"] = c.text or ""

    candidates = sorted(by_doc.values(), key=lambda d: -d["top_score"])
    if len(candidates) < _DISAMBIG_MIN_DOCS:
        return None

    top = candidates[0]
    second = candidates[1]
    if top["top_score"] < _DISAMBIG_MIN_TOP_SCORE:
        return None

    # Score-spread check: if top much better than runner-up, NOT ambiguous.
    gap = top["top_score"] - second["top_score"]
    denom = abs(top["top_score"]) or 1.0
    if (gap / denom) > _DISAMBIG_SCORE_GAP:
        return None

    # Shape for the frontend. Limit to 4 candidates — more than that and
    # the user is just "give me all docs", not clarifying.
    out = []
    for cand in candidates[:4]:
        hint_raw = (cand["top_chunk_text"] or "").strip().replace("\n", " ")
        hint = (hint_raw[:160] + "…") if len(hint_raw) > 160 else hint_raw
        out.append(
            {
                "doc_id": cand["doc_id"],
                "filename": cand["filename"],
                "label": _prettify_filename(cand["filename"]),
                "hint": hint,
                "top_score": round(cand["top_score"], 3),
                "chunk_count": cand["chunk_count"],
            }
        )
    return out


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

        # ── Agent: cross-doc comparison short-circuit (Tier 2.2) ─────────
        # User clicked "Compare all" on the disambiguation card. Run
        # retrieval + generation ONCE per doc, scoped to that single
        # doc, in parallel. Emit a `comparison` event with all answers
        # + their sources; persist as a single ChatTurn with answer_mode
        # = "comparison". Skips streaming — N parallel token streams is
        # a UX disaster; we deliver all answers in one payload.
        if (
            req.compare_doc_ids
            and len(req.compare_doc_ids) >= 2
            and not req.preferred_doc_id
        ):
            t_cmp = time.perf_counter()
            # Clamp to max 4 to keep latency bounded (4 × 3s each, in
            # parallel, ≈ 3-4s wall-clock with slowest doc).
            compare_ids = req.compare_doc_ids[:4]
            results = await _run_comparison(
                req.query, compare_ids, user, req
            )
            cmp_latency = int((time.perf_counter() - t_cmp) * 1000)
            retrieve_ms = cmp_latency  # aggregated for analytics
            generate_ms = cmp_latency

            yield {
                "event": "comparison",
                "data": json.dumps(
                    {"query": req.query, "columns": results}
                ),
            }

            # Build a human-readable summary for the ChatTurn content
            # field (used when the thread is replayed or summarised).
            summary_lines = [f"Compared {len(results)} document(s):"]
            for r in results:
                label = _prettify_filename(r.get("filename", "") or "")
                summary_lines.append(f"• {label} → {len(r.get('sources', []))} sources")
            full_answer = "\n".join(summary_lines)
            sources_json = json.dumps({"comparison": results})
            answer_mode = "comparison"

            # Persist turn + audit row directly here (we bypass the shared
            # finally block because the cached-path state doesn't apply).
            try:
                models.append_turn(
                    thread_id=thread_id,
                    role="user",
                    content=req.query,
                )
                models.append_turn(
                    thread_id=thread_id,
                    role="assistant",
                    content=full_answer,
                    sources_json=sources_json,
                    refused=False,
                    answer_mode=answer_mode,
                    faithfulness=-1.0,
                )
                models.touch_thread(thread_id)
                cited_doc_ids = sorted({r.get("doc_id", "") for r in results if r.get("doc_id")})
                models.write_audit(
                    models.AuditLog(
                        user_id=user.id,
                        username=user.username,
                        user_level=user.level,
                        query=req.query,
                        refused=False,
                        returned_chunks=sum(len(r.get("sources", [])) for r in results),
                        allowed_doc_ids=",".join(cited_doc_ids),
                        answer_mode=answer_mode,
                        latency_retrieve_ms=retrieve_ms,
                        latency_rerank_ms=0,
                        latency_generate_ms=generate_ms,
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
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "ok": True,
                        "answer_mode": answer_mode,
                        "thread_id": thread_id,
                        "cached": False,
                        "latency_ms": {
                            "retrieve": retrieve_ms,
                            "rerank": 0,
                            "generate": generate_ms,
                            "total": int((time.perf_counter() - t_total) * 1000),
                        },
                        "tokens": {"prompt": 0, "completion": 0},
                        "corrective_retries": 0,
                        "faithfulness": -1.0,
                        "confidence": None,
                        "rbac_blocked": False,
                        "citation_check": None,
                    }
                ),
            }
            return

        # ── Agent: apply preferred_doc_id before any retrieval ──────────
        # When the user clicks a doc in the disambiguation card, the
        # frontend sends the retry with preferred_doc_id set. We fold it
        # into req.doc_ids (a hard filter applied at retrieve time) so
        # the whole pipeline scopes to that single doc. We also set
        # skip_disambiguation=True implicitly so we never ping-pong.
        # Persist the choice on the prior disambiguate turn so a reload
        # renders the card as already-decided.
        if req.preferred_doc_id:
            req.doc_ids = [req.preferred_doc_id]
            req.skip_disambiguation = True
            if thread_id:
                try:
                    models.mark_last_disambiguation_chosen(
                        thread_id, req.preferred_doc_id
                    )
                except Exception:
                    pass

        # ── 2. Cache lookup ──────────────────────────────────────────────
        cache_settings = {
            "hyde": req.use_hyde,
            "rerank": req.use_rerank,
            "k": req.top_k,
            "sections": req.section_filter or [],
            "preferred_doc_id": req.preferred_doc_id or "",
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
        # `chunks` may not be populated on the cached-hit or disambiguate
        # paths; initialise to empty so the confidence-scoring helper
        # called at the bottom doesn't NameError. Re-assigned inside the
        # grounded retrieval branch.
        chunks: list = []
        # Agent — RBAC transparency signal. True when the query DID match
        # a doc in the corpus but at a clearance above the caller's level,
        # forcing `unknown` (non-L4) or `refused` (L4). Lets the frontend
        # swap the bland "no answer" card for a "request access" card.
        rbac_blocked = False
        # Citation verification result (Tier 1.1). Populated post-stream
        # for grounded answers. None on non-grounded modes.
        citation_check: dict | None = None

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
                # ── Agent: kick off intent classification in the background.
                # Runs in parallel with retrieval so the LLM latency is
                # absorbed by the retrieve step. We'll await it just
                # before streaming and emit the `intent` event. Skipped
                # for very short queries (< 3 non-whitespace chars) and
                # when the user supplied an `override_intent` from the
                # Intent Mirror pill.
                intent_task: asyncio.Task | None = None
                if req.override_intent and req.override_intent.strip():
                    # User already told us what they meant — just echo it.
                    pass
                elif len((req.query or "").strip()) >= 3:
                    intent_task = asyncio.create_task(
                        _classify_intent(req.query.strip())
                    )

                # ── 2b. Conversational contextualization ──────────────────
                # If the user's message is a follow-up ("tell me more",
                # "why?", pronoun-leading, etc.) and we have history, ask an
                # LLM to rewrite it into a self-contained question so the
                # retriever has something concrete to match against. Without
                # this step, "tell me in more detail" retrieves nothing and
                # the answer collapses to "no confident answer".
                # When `override_intent` is set by the user (from the
                # Intent Mirror pill edit), we use it directly as the
                # search query — they've told us explicitly what they meant.
                search_query = (req.override_intent or req.query).strip() or req.query
                if req.history and _looks_like_followup(req.query) and not req.override_intent:
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
                # Tier 3.3 — if the query is recency-sensitive ("latest",
                # "Q4 2024", etc.), ask retrieval to boost newer docs.
                from src.pipelines.retrieval_pipeline import _is_recency_sensitive
                prefer_recent = _is_recency_sensitive(search_query)

                # Sumith's eval feedback (2026-04-16): top_k=5 is too
                # small for compound multi-part questions — half the
                # sub-questions fall off the shortlist even though the
                # answer IS in the corpus. Auto-expand top_k when the
                # query looks compound. Simple questions stay at base
                # top_k for speed.
                sub_q_count = _estimate_subquestions(search_query)
                original_top_k = req.top_k
                if sub_q_count > 1:
                    req.top_k = _expanded_top_k(req.top_k, sub_q_count)
                chunks, retrieve_ms = await _retrieve_multi(
                    queries, user.level, req, caller_role=user.role,
                    prefer_recent=prefer_recent,
                )
                if req.top_k != original_top_k:
                    yield {
                        "event": "topk_expanded",
                        "data": json.dumps({
                            "from": original_top_k,
                            "to": req.top_k,
                            "sub_questions": sub_q_count,
                        }),
                    }
                if prefer_recent:
                    yield {
                        "event": "recency_boost",
                        "data": json.dumps({"applied": True, "query": search_query}),
                    }

                # Rerank already done inside retrieve; we expose the split only
                # for observability. Approximation: generate_ms and rerank_ms
                # are not cleanly separable under the current pipeline, so we
                # attribute ~40% of retrieve_ms to rerank as a sensible split.
                rerank_ms = int(retrieve_ms * 0.4)

                # ── 4. Relevance gate ─────────────────────────────────────
                grounded_ok = bool(chunks) and _passes_bar(chunks)

                # ── 4b. Agent: disambiguate when top chunks span distinct
                # docs with comparable scores. Fires ONLY for grounded-
                # quality retrievals — weak retrievals still fall through
                # to corrective / general / unknown as before. Skipped
                # when the caller already pinned a preferred doc, or when
                # doc_ids was pre-scoped (single-doc query). We do NOT
                # `return` — the mode-switch block (step 7) handles the
                # `disambiguate` branch, so the shared `finally` still
                # persists turns + writes the audit row.
                disambig_candidates: list[dict] | None = None
                if (
                    grounded_ok
                    and not req.skip_disambiguation
                    and not req.preferred_doc_id
                    and (not req.doc_ids or len(req.doc_ids) != 1)
                    # Compound questions (≥3 sub-parts) should NOT
                    # trigger disambiguation — the user explicitly
                    # asked for content spanning multiple docs. Forcing
                    # them to pick ONE doc drops the other sub-parts.
                    # Let the expanded top_k handle it: 12 chunks can
                    # cover 4 docs × 3 chunks each without blending.
                    and sub_q_count < 3
                ):
                    disambig_candidates = _detect_doc_ambiguity(chunks)

                # ── 5. Corrective RAG — one retry if first pass weak ─────
                # Only fire for substantive queries (≥2 content words) — avoids
                # wasting a rewrite LLM call on "hello", "hi", etc.
                # Skip entirely when we're about to disambiguate — the
                # chunks were already strong enough to trigger it.
                if (
                    req.use_corrective
                    and not grounded_ok
                    and not disambig_candidates
                    and _is_substantive_query(req.query)
                ):
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
                # Routing matrix:
                #   has_higher_match=True  → L4: refused · non-L4: unknown
                #     (don't leak that a higher-clearance doc exists)
                #   has_higher_match=False → general for ANY role
                #     (it's safe — the question matches NOTHING in the
                #     corpus at any clearance, so there's nothing to leak.
                #     Refusing here just frustrates users with off-topic
                #     questions like "atomic weight of hydrogen".)
                if disambig_candidates:
                    answer_mode = "disambiguate"
                elif grounded_ok:
                    answer_mode = "grounded"
                elif not _looks_like_real_query(req.query):
                    answer_mode = "unknown"
                else:
                    probe, probe_ms = await _retrieve_with_timing(
                        req.query, user.level, req, bypass=True
                    )
                    retrieve_ms += probe_ms
                    has_higher_match = bool(probe) and _passes_bar(probe)
                    if has_higher_match:
                        answer_mode = "refused" if user.level >= 4 else "unknown"
                        rbac_blocked = True
                    else:
                        answer_mode = "general"

                # ── Agent: emit intent restatement right before streaming.
                # Skip for disambiguate (the picker IS the intent check)
                # and for answers where the agent's interpretation isn't
                # meaningful (unknown/refused — no real answer to frame).
                if answer_mode in {"grounded", "general"}:
                    restatement = ""
                    if req.override_intent and req.override_intent.strip():
                        restatement = f"Using your edit: “{req.override_intent.strip()[:240]}”"
                    elif intent_task is not None:
                        try:
                            restatement = await asyncio.wait_for(
                                asyncio.shield(intent_task), timeout=2.0
                            )
                        except (asyncio.TimeoutError, Exception):
                            restatement = ""
                    if restatement:
                        yield {
                            "event": "intent",
                            "data": json.dumps(
                                {
                                    "intent": restatement,
                                    "original": req.query,
                                    "edited": bool(req.override_intent),
                                }
                            ),
                        }

                # Cancel the intent task if it's still running (non-grounded
                # path took over, e.g. disambiguate or refused).
                if intent_task is not None and not intent_task.done():
                    intent_task.cancel()

                # ── 7. Emit + stream ─────────────────────────────────────
                t_gen = time.perf_counter()
                if answer_mode == "disambiguate":
                    # No LLM call — emit the candidates and let the
                    # frontend render a picker. `sources_json` carries
                    # the candidate list so Audit + thread replay can
                    # reconstruct what was offered.
                    full_answer = (
                        "Your question could match these documents. "
                        "Tap one to scope the answer to just that doc."
                    )
                    sources_json = json.dumps({"candidates": disambig_candidates})
                    yield {
                        "event": "disambiguate",
                        "data": json.dumps(
                            {
                                "query": req.query,
                                "candidates": disambig_candidates,
                                "message": full_answer,
                            }
                        ),
                    }
                elif answer_mode == "grounded":
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
                    yield {
                        "event": "refused",
                        "data": json.dumps(
                            {"message": msg, "rbac_blocked": rbac_blocked}
                        ),
                    }

                else:  # unknown
                    if rbac_blocked:
                        msg = (
                            "I couldn't find an answer you're allowed to see. "
                            "A document above your clearance level may cover this — "
                            "request access below to let your manager review."
                        )
                    else:
                        msg = (
                            "I don't have a confident answer for that question. Try "
                            "rephrasing, or check the Knowledge base tab for what's "
                            "available."
                        )
                    full_answer = msg
                    yield {
                        "event": "unknown",
                        "data": json.dumps(
                            {"message": msg, "rbac_blocked": rbac_blocked}
                        ),
                    }

                generate_ms = int((time.perf_counter() - t_gen) * 1000)

                # Token estimates
                tokens_prompt = _approx_tokens(
                    SYSTEM_PROMPT + req.query + (sources_json or "")
                )
                tokens_completion = _approx_tokens(full_answer)

                # ── 8. Faithfulness (grounded only, skippable via flag) ──
                if req.use_faithfulness and answer_mode == "grounded" and full_answer.strip():
                    faithfulness = await _faithfulness_score(full_answer, chunks)

                # ── 8a. Citation verification (NEW — Tier 1.1) ──────────
                # Catch fabricated [Source N] tags (numbers that don't
                # match any actual chunk) AND weak overlaps (cited but
                # the sentence shares no substantive words with chunk).
                # Cheap (regex + set ops, no LLM call). Always-on for
                # grounded answers — the user gets a visible warning chip
                # if anything's off.
                citation_check: dict | None = None
                if answer_mode == "grounded" and full_answer.strip() and chunks:
                    citation_check = _verify_citations(full_answer, chunks)
                    if citation_check["fabricated"] or citation_check["weak"]:
                        yield {
                            "event": "citation_check",
                            "data": json.dumps(citation_check),
                        }

                # ── 8b. Post-hoc demotion: grounded → (general | unknown)
                # when the LLM itself refused on retrieved chunks. The
                # demotion mirrors the primary mode classifier: bypass
                # probe decides the route — same metadata-leak protection,
                # same useful general-knowledge fallback for off-corpus
                # questions, applied uniformly across roles.
                if answer_mode == "grounded" and _answer_is_refusal(full_answer):
                    returned_chunks = 0
                    cited_doc_ids = []
                    sources_json = ""
                    probe2, probe2_ms = await _retrieve_with_timing(
                        req.query, user.level, req, bypass=True
                    )
                    retrieve_ms += probe2_ms
                    higher_match2 = bool(probe2) and _passes_bar(probe2)
                    if higher_match2:
                        # Higher-clearance doc would have answered. Don't
                        # leak its existence — show 'unknown' (or 'refused'
                        # for L4 with the diagnostic).
                        answer_mode = "refused" if user.level >= 4 else "unknown"
                        rbac_blocked = True
                    else:
                        # Nothing anywhere in the corpus. Re-stream the
                        # answer with the general-knowledge prompt so the
                        # user actually gets a useful response.
                        answer_mode = "general"
                        full_answer = ""
                        faithfulness = -1.0
                        yield {"event": "answer_reset", "data": "{}"}
                        yield {
                            "event": "general_mode",
                            "data": json.dumps(
                                {
                                    "message": "Not in your corpus — falling back to general knowledge."
                                }
                            ),
                        }
                        async for delta in _stream_general(req.query, req.history):
                            full_answer += delta
                            yield {"event": "token", "data": json.dumps({"delta": delta})}
                        tokens_completion = _approx_tokens(full_answer)

                # ── 9. Cache it ──────────────────────────────────────────
                # Don't cache disambiguations — the user hasn't gotten a
                # real answer yet, and re-running retrieval on the next
                # identical query is cheap and keeps the candidate list
                # fresh (new uploads change which docs are candidates).
                if answer_mode != "disambiguate":
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

        # Agent: composite confidence chip value (grounded answers only).
        # On cached replays we rehydrate a lightweight top-chunk from the
        # stored sources_json so the chip still shows without re-running
        # retrieval.
        confidence_chunks = chunks if chunks else []
        if not confidence_chunks and answer_mode == "grounded" and sources_json:
            try:
                import types as _types
                parsed = json.loads(sources_json)
                if isinstance(parsed, list) and parsed:
                    top = parsed[0]
                    confidence_chunks = [
                        _types.SimpleNamespace(
                            rerank_score=top.get("rerank_score"),
                            rrf_score=top.get("rrf_score", 0.0),
                        )
                    ]
            except Exception:
                confidence_chunks = []
        confidence = _compute_confidence(
            answer_mode=answer_mode,
            chunks=confidence_chunks,
            faithfulness=faithfulness,
        )

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
                    "confidence": confidence,
                    "rbac_blocked": rbac_blocked,
                    "citation_check": citation_check,
                }
            ),
        }

    return EventSourceResponse(event_generator())


# ─── Access Request endpoint ────────────────────────────────────────────────
# When a non-L4 user sees an "RBAC-blocked" unknown card and clicks
# "Request access", the frontend POSTs here. We persist a lightweight
# audit trail so executives can review requests in the Audit tab. This
# is deliberately minimal — no email, no workflow — the point is to let
# the student demo the interaction without building a request-tracking
# system. Extendable later without touching the UI contract.


class AccessRequestPayload(BaseModel):
    query: str
    reason: str | None = None


@router.post("/access-request")
async def access_request(
    req: AccessRequestPayload,
    user: CurrentUser = Depends(chat_rate_limit),
):
    q = (req.query or "").strip()[:500]
    reason = (req.reason or "").strip()[:500]
    if not q:
        return {"ok": False, "message": "query required"}
    try:
        models.write_audit(
            models.AuditLog(
                user_id=user.id,
                username=user.username,
                user_level=user.level,
                query=f"[access-request] {q}" + (f" — {reason}" if reason else ""),
                refused=True,
                returned_chunks=0,
                allowed_doc_ids="",
                answer_mode="access_request",
                latency_retrieve_ms=0,
                latency_rerank_ms=0,
                latency_generate_ms=0,
                latency_total_ms=0,
                tokens_prompt=0,
                tokens_completion=0,
                cached=False,
                corrective_retries=0,
                faithfulness=-1.0,
            )
        )
    except Exception:
        return {"ok": False, "message": "failed to log request"}
    return {
        "ok": True,
        "message": f"Access request logged for {user.username}. A manager will review.",
    }
