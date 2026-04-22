"""Corpus-agnostic policy-rule extractor.

Replaces the hardcoded `TECHNOVA CORPUS CONSTANTS` block with a per-corpus
fact index. At upload time, every PDF/DOCX gets scanned for numerical
rules (thresholds, percentages, currency amounts, flag words) and the
results are persisted to `corpus_facts`. At query time, the analytics
agent retrieves only the facts relevant to the current question.

This lets the system answer policy-aware questions on ANY uploaded
corpus — a hospital compliance dataset, a retail P&L, whatever sir
throws at it — without touching the prompt template.

Design:
  • LLM-based extraction per document (one call per doc at upload).
    We accept the latency cost once, offline to the user's interaction.
  • Keyword-first retrieval at query time (fast, cheap, no LLM call).
    Upgradeable to embedding-based retrieval by embedding `statement`
    into the main Qdrant collection — deferred until keyword recall
    proves insufficient.
  • Results injected as a "POLICY FACTS FROM YOUR DOCUMENTS" section
    into the multi-table analytics prompt, each with PDF citation.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from src.core import store
from src.pipelines.generation_pipeline import _complete_chat


# ── LLM prompt for fact extraction ────────────────────────────────────────

_FACT_EXTRACTION_PROMPT = """You are reading a business document to extract
REFERENCEABLE NUMERICAL FACTS — any specific number, rule, threshold, or
reported figure a data analyst might need to cite in a SQL/pandas query.

TWO categories count:

1) RULES / POLICIES (forward-looking):
  • "retention bonuses up to 30% of annual CTC"
  • "on-call stipend of INR 5,000 per week for primary"
  • "departments with completion rates below 90% are flagged"
  • "ESOPs granted at L5 and above"
  • "target: 3,500 paying enterprise customers by Q2 FY2027"
  • "38% of the ₹485 crore product budget allocated to AI/ML"
  • "Vietnam and Indonesia flagged as data-localization risk"

2) REPORTED FIGURES / REFERENCE VALUES (historical but load-bearing):
  • "Engineering utilized 94.7% of its Q4 budget of INR 210 crores"
  • "Q4 cloud infrastructure overspend was INR 12.3 crores"
  • "16 NVIDIA A100 GPU nodes running a single AWS EKS cluster"
  • "current enterprise customer count is 2,847"
  • "FY25-26 GPU compute spend totalled INR 133.99 crores"
  • "8-week intensive response window Oct-Nov 2025 after INC-2025-0847"

Both categories get extracted — they're the ground truth for THIS corpus.

What DOESN'T count:
  • Generic prose, mission statements, team bios, background narratives.
  • Prose with no specific number or named entity attached.
  • Illustrative examples clearly marked "for example" / "e.g." that aren't
    the actual policy or figure.

Output STRICT JSON — a list of objects, no prose, no markdown fences.
Each object:
  {
    "statement":  "<short natural-language sentence capturing the fact>",
    "section":    "<e.g. §3, Step 2, or empty string>",
    "keywords":   ["word1","word2",...],   // 3-8 lowercase search terms,
                                            // prefer domain nouns + units
    "quantity":   <number or null>,        // numeric part (pick the main one)
    "unit":       "<%, INR_lakhs, INR_crores, weeks, employees, GPUs, ... or empty>",
    "kind":       "<threshold | cap | rate | policy | target | reported | reference>"
  }

Extract AT MOST 30 facts per document. If the document is truly prose-only
(no numbers, no rules, no reference values), return [].

DOCUMENT TEXT:
{text}

OUTPUT (JSON array only, no other text):"""


# Regex for fast prefilter — only LLM-extract docs that actually contain
# at least one rule-shaped sentence. Cuts API spend on prose-only docs.
# Match several rule shapes; order-agnostic currency/number pairing.
_RULE_SNIFFER = re.compile(
    r"(?:"
    # Number followed by unit:  "30% of", "210 crore", "5,000 INR"
    r"\b[0-9][0-9,\.]*\s*(?:%|percent|crore|lakh|million|billion|inr|rs\.?|usd|weeks?|days?|months?|years?)\b"
    # OR unit followed by number:  "INR 5,000", "₹210 Cr", "Rs. 25,000", "$500"
    r"|(?:\binr\b|\brs\.?\b|\busd\b|₹|\$)\s*[0-9][0-9,\.]*"
    # OR threshold language
    r"|\b(?:at\s+least|at\s+most|not\s+(?:less|more)\s+than|up\s+to|capped\s+at|below|above|exceed|exceeds|over|under)\b"
    # OR policy verbs / status words
    r"|\b(?:flagged|required|mandatory|eligible|granted|target|cap|stipend|bonus|threshold|allocat|reimburs|limit)"
    # OR ordinal / versioned levels ("L5 and above", "Tier 1")
    r"|\bl[1-9]\b|\btier\s+[0-9]"
    r")",
    re.IGNORECASE,
)


def _has_rule_shaped_content(text: str) -> bool:
    """Cheap pre-check before calling the LLM. Returns True if the
    document contains at least one sentence that looks like it could
    carry a rule. Saves an LLM call on pure-prose docs (about/biographies).

    False positives are cheap (one extra LLM call that returns []).
    False negatives are expensive (entire document's rules go missing).
    So we err on the permissive side — require only 1 hit, not 2.
    """
    if not text or len(text) < 100:
        return False
    return _RULE_SNIFFER.search(text) is not None


# ── Public API ────────────────────────────────────────────────────────────

async def extract_facts(
    *, text: str, doc_id: str, filename: str, max_chars: int = 40_000
) -> list[store.CorpusFact]:
    """Extract policy rules from a document's plaintext.

    Caller is responsible for persistence — returns fresh (unsaved)
    CorpusFact rows so the caller can choose transactional semantics.

    Safe on any document — returns [] if the text is prose-only, if
    the LLM call fails, or if the response isn't parseable JSON. We
    never block ingestion on this step.
    """
    if not _has_rule_shaped_content(text):
        return []

    # Clip to avoid blowing the context window on huge PDFs. Most policy
    # rules cluster in the first few pages of a typical handbook.
    trimmed = text[:max_chars]
    prompt = _FACT_EXTRACTION_PROMPT.replace("{text}", trimmed)

    try:
        raw = await _complete_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=2000, temperature=0.0,
        )
    except Exception:
        return []

    # Tolerate markdown fences and leading/trailing prose from chatty models
    cleaned = _strip_json_fence(raw)
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []

    out: list[store.CorpusFact] = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        stmt = str(item.get("statement") or "").strip()
        if not stmt:
            continue
        kws_raw = item.get("keywords") or []
        if isinstance(kws_raw, str):
            kws_raw = [kws_raw]
        keywords = ",".join(
            sorted({str(k).strip().lower() for k in kws_raw if str(k).strip()})
        )
        qty = item.get("quantity")
        try:
            qty_val = float(qty) if qty is not None and qty != "" else None
        except (TypeError, ValueError):
            qty_val = None
        # Stable deterministic id so re-extraction overwrites instead of
        # duplicating. Hash(doc_id + statement) — different docs with
        # identical statements stay separate because doc_id is in the mix.
        fid = hashlib.sha1(f"{doc_id}|{stmt}".encode("utf-8")).hexdigest()[:16]
        out.append(
            store.CorpusFact(
                fact_id=fid,
                doc_id=doc_id,
                filename=filename,
                section=str(item.get("section") or "").strip()[:64],
                statement=stmt[:500],
                keywords=keywords[:400],
                quantity=qty_val,
                unit=str(item.get("unit") or "").strip()[:32],
                kind=str(item.get("kind") or "").strip().lower()[:32],
            )
        )
    return out


def _strip_json_fence(raw: str) -> str:
    """Remove ```json ... ``` wrappers and any pre/post prose that a
    chatty LLM (e.g. gpt-5.4 with reasoning) insists on adding."""
    if not raw:
        return ""
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    # Find the first '[' and last ']' — anything outside is junk
    start = s.find("[")
    end = s.rfind("]")
    if start >= 0 and end > start:
        return s[start : end + 1]
    return s


def search_facts(
    *,
    query: str,
    doc_ids: list[str] | None = None,
    max_doc_level: int | None = None,
    limit: int = 12,
) -> list[store.CorpusFact]:
    """Keyword-based retrieval over the fact index.

    Scores facts by how many query tokens hit their `keywords` field
    plus `statement`. Returns top `limit` sorted by score descending.
    Zero-LLM — cheap enough to run on every analytics query.

    Upgrade path: swap the scoring for an embedding-based cosine sim
    against a fact-specific Qdrant collection if recall becomes a
    bottleneck on very large corpora.
    """
    if not query:
        return []
    facts = store.list_corpus_facts(doc_ids=doc_ids, max_doc_level=max_doc_level)
    if not facts:
        return []
    q_tokens = _tokenize(query)
    if not q_tokens:
        return facts[:limit]
    scored: list[tuple[float, store.CorpusFact]] = []
    for f in facts:
        kw_set = {t.strip() for t in (f.keywords or "").split(",") if t.strip()}
        stmt_tokens = _tokenize(f.statement or "")
        score = 0.0
        for t in q_tokens:
            if t in kw_set:
                score += 2.0
            if t in stmt_tokens:
                score += 1.0
        if score > 0:
            scored.append((score, f))
    scored.sort(key=lambda sf: sf[0], reverse=True)
    return [f for _, f in scored[:limit]]


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens of length >=3. Keeps domain-specific words
    like 'esop' / 'arr' / 'ctc' which are all 3+ chars."""
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def format_facts_for_prompt(facts: list[store.CorpusFact]) -> str:
    """Render retrieved facts into a prompt-ready block.

    Replaces the old hardcoded `TECHNOVA CORPUS CONSTANTS` section. The
    block is only added when facts exist — if the uploaded corpus has
    no extracted rules, the prompt stays clean and nothing forces the
    LLM to fabricate constants.
    """
    if not facts:
        return ""
    lines: list[str] = [
        "=== POLICY FACTS FROM YOUR UPLOADED DOCUMENTS ===",
        "These numerical rules were extracted from the PDFs in this",
        "corpus. Cite them when they apply to the question. Prefer these",
        "over anything you 'recall' from training — they are the ground",
        "truth for THIS dataset.",
        "",
    ]
    for f in facts:
        cite = f"({f.filename}"
        if f.section:
            cite += f" {f.section}"
        cite += ")"
        qty = ""
        if f.quantity is not None:
            unit = f" {f.unit}" if f.unit else ""
            qty = f"  [value: {f.quantity}{unit}]"
        lines.append(f"  • {f.statement}{qty} {cite}")
    lines.append("")
    return "\n".join(lines)
