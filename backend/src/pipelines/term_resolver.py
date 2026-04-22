"""Schema-aware business-term resolver.

A cheap pre-flight LLM call that inspects the CURRENT corpus's actual
column values and maps the user's colloquial phrases onto concrete filter
predicates grounded in THAT data.

Problem this solves:
  The business-term glossary in the prompt is static. "Biggest accounts"
  → 'Tier 1' works for TechNova, but if sir uploads a corpus where
  customer size is expressed as `segment IN {Enterprise, SMB, Startup}`,
  the static rule is wrong. The resolver inspects
  `df_customers['tier'].unique()` at query time and picks the actual
  top category for THIS corpus — no hardcoding.

Shape of a resolution:
  {
    "phrase":  "biggest accounts",
    "column":  "df_customers['tier']",
    "filter":  "df_customers['tier'] == 'Tier 1'",
    "reason":  "tier column contains {Tier 1, Tier 2, Tier 3}; Tier 1
                is the top-of-stack segment"
  }

The resolved filters are injected into the code-gen prompt as a section
the LLM can copy-paste. Keeps the main prompt short and keeps domain
knowledge out of the template.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.pipelines.generation_pipeline import _complete_chat


# ── Build a compact "value samples" summary the LLM can reason over ──────

# Columns that almost never carry load-bearing categorical semantics —
# exclude from the sampled summary so we don't waste tokens on IDs and
# long free-text fields. Everything else gets a sample.
_BORING_COL_SUFFIXES = ("_id", "_ID", "_email", "_phone", "_url", "_ip", "_uuid")
_BORING_COL_EXACT = {"email", "phone", "url", "notes", "description", "_sheet"}


def _column_is_worth_sampling(name: str, dtype_str: str) -> bool:
    n = str(name)
    if n in _BORING_COL_EXACT:
        return False
    if any(n.endswith(s) for s in _BORING_COL_SUFFIXES):
        return False
    # Numeric dtypes — include a min/max/median summary, not unique values
    return True


def _summarize_column(series: pd.Series, max_values: int = 12) -> str:
    """Compact one-liner describing what values live in this column.

    For string/categorical: "Tier 1, Tier 2, Tier 3"
    For numeric: "min 0, median 24, max 128"
    For datetime: "range 2025-01-01 .. 2026-04-21"
    Returns "" for boring / unhelpful columns so caller can skip them.
    """
    dtype = str(series.dtype)
    non_null = series.dropna()
    if non_null.empty:
        return "(all null)"
    if pd.api.types.is_numeric_dtype(non_null):
        try:
            lo = non_null.min()
            hi = non_null.max()
            md = non_null.median()
            return f"numeric: min={lo:g}, median={md:g}, max={hi:g}"
        except Exception:
            return f"numeric, {len(non_null)} rows"
    if pd.api.types.is_datetime64_any_dtype(non_null):
        return f"datetime: {non_null.min()} .. {non_null.max()}"
    # String/object — show unique set if small, else top-K by frequency
    try:
        uniq = non_null.astype(str).str.strip()
        n_unique = uniq.nunique()
        if n_unique <= max_values:
            vals = sorted(uniq.unique().tolist())
            return "categorical: " + ", ".join(repr(v)[:40] for v in vals)
        top = uniq.value_counts().head(max_values)
        return (
            f"text ({n_unique} unique), top: "
            + ", ".join(f"{repr(k)[:40]} ({v})" for k, v in top.items())
        )
    except Exception:
        return f"{dtype}, {len(non_null)} rows"


def _build_schema_preview(dfs: dict[str, pd.DataFrame], max_cols_per_table: int = 20) -> str:
    """Emit a compact per-table/per-column summary the LLM can reason over.

    Keeps it under ~4k tokens even for large corpora by capping columns
    per table and skipping obviously-boring ones (IDs, emails).
    """
    lines: list[str] = []
    for name, df in dfs.items():
        clean_cols = [
            c for c in df.columns
            if not str(c).startswith("_")
            and not str(c).startswith("Unnamed")
            and not str(c).startswith("TechNova Inc.")
        ]
        lines.append(f"── df_{name} ({df.shape[0]} rows × {len(clean_cols)} cols) ──")
        shown = 0
        for col in clean_cols:
            if shown >= max_cols_per_table:
                lines.append(f"  ... ({len(clean_cols) - shown} more columns not shown)")
                break
            if not _column_is_worth_sampling(col, str(df[col].dtype)):
                continue
            summary = _summarize_column(df[col])
            if summary:
                lines.append(f"  {col}: {summary}")
                shown += 1
        lines.append("")
    return "\n".join(lines)


# ── The resolver prompt + call ───────────────────────────────────────────

_RESOLVER_PROMPT = """You are grounding a business question against the ACTUAL
corpus the analyst is querying. Identify every colloquial / business phrase
in the question that needs mapping to a concrete column + filter, and
propose the mapping using ONLY columns + values that exist in the schema
below.

You are NOT writing the full analysis — only resolving ambiguous phrases
so the next step can write correct code. Keep resolutions short and
precise. Ground every filter in a value you can see in the schema preview.

CRITICAL: policy facts below are extracted from the uploaded PDFs. When
the same word ("senior", "flagged", "critical") has MULTIPLE plausible
thresholds in different policy docs, pick the one whose rule VERB
matches the question's verb:
  • question mentions laptops/hardware      → use IT/Asset policy rule
  • question mentions ESOPs/compensation    → use Salary-Structure rule
  • question mentions on-call/incidents     → use OnCall/Incident rule
  • question mentions compliance/training   → use Training rule
If no policy fact clearly matches, fall back to the most commonly used
level threshold in the column's value distribution.

EVEN MORE CRITICAL — POLICY FACTS WIN OVER COLUMN EXPLORATION:
If a policy fact names a SPECIFIC value set (e.g. "Vietnam and Indonesia
are flagged as data-localization risk", or "Tier 1 is the enterprise tier",
or "mandatory modules are InfoSec Awareness, POSH, ABAC, DPDP Act 2023"),
your resolution for that concept MUST be EXACTLY those values — do NOT
broaden to every related value you see in the column.

Wrong (over-broadening):
  question: "markets where data localization could blow up on us"
  fact:     "Vietnam and Indonesia are flagged as data-localization risk"
  schema:   country column has {India, Indonesia, Japan, Korea, Singapore,
                                 Thailand, Vietnam}
  BAD:  country.isin(['India','Indonesia','Japan','Korea','Singapore','Thailand','Vietnam'])
        (picked "all APAC countries" because they're all in the schema)
  GOOD: country.isin(['Vietnam','Indonesia'])
        (exactly what the policy fact says)

Wrong (under-specification):
  question: "biggest accounts in regulated Asian markets"
  schema:   tier column has {Tier 1, Tier 2, Tier 3}; country has {India,
            Japan, Korea, Vietnam, Indonesia, Singapore}
  BAD:  country.isin(list-every-Asian-country) + no tier filter
  GOOD: country.isin(['India','Japan','South Korea'])   # regulated = strong data-protection regimes
        AND tier == 'Tier 1'

When in doubt between NARROW and BROAD, pick NARROW. Under-matching a
business filter is ALWAYS better than over-matching — the analyst can
loosen the filter if they want more rows, but a silently broadened
filter produces answers that LOOK reasonable while being wrong.

PREFER DIRECT COLUMNS OVER DERIVED AGGREGATIONS:
When the question names a metric ("revenue", "cost", "headcount",
"compensation"), look for a column whose name contains that word
(or close synonym like "arr_inr_lakhs" for revenue, "total_ctc" for
compensation). If a matching column exists on an entity table, USE
IT — do not build a multi-step aggregation from a transaction table.

Wrong (over-derivation):
  question: "how much revenue do we have in Vietnam?"
  schema: df_customers has column 'arr_inr_lakhs' (annualised recurring
          revenue per customer); df_financial_transactions has
          'amount_inr_crores' with period_quarter/subcategory
  BAD:  transactions.filter(period='FY27-Q1').groupby('country').sum()
        (hunts for future transactions that don't exist in the data)
  GOOD: customers[customers.country=='Vietnam']['arr_inr_lakhs'].sum()
        (direct revenue column on the entity being asked about)

When the user says "revenue in markets / regions / industries", they
mean the CURRENT BOOKED / RECURRING revenue for those markets, not a
forward-projected transaction forecast. ARR IS next-year revenue by
definition — no period filter needed.

Examples of phrases to resolve:
  "biggest accounts"        → tier / segment / ARR rank — pick whichever
                              column exists and say what value counts
                              as "biggest"
  "senior staff"            → level / grade column — pick the value set
                              that means "senior" in THIS corpus
  "regulated Asian markets" → country column — list the specific
                              countries in the corpus that fit
  "behind on training"      → which column carries completion status +
                              what threshold counts as "behind"
  "flagged vendors"         → risk / status column — list the values
                              that count as flagged
  "last year"               → date column — concrete year anchor
  "without ESOPs"           → level column value set that excludes
                              ESOP-eligible tiers
  "engineers" (verb-dependent)
                            → dept column. Narrow to the Engineering
                              dept by default. Broaden to the full
                              technical department set ONLY if the
                              question is about incidents, on-call,
                              security, or reliability.

If a phrase is already unambiguous (e.g. a specific number, an exact
column name the user already typed), skip it.

TODAY: {today}. "last year" = calendar year today.year - 1.

RELEVANT POLICY FACTS FROM THIS CORPUS (use these to disambiguate
multi-meaning words like "senior" or "flagged"):
{policy_facts}

SCHEMA PREVIEW (actual values from this corpus):
{schema_preview}

QUESTION:
{query}

Return STRICT JSON — no prose, no markdown fence:
{{
  "resolutions": [
    {{
      "phrase": "<the colloquial phrase from the question>",
      "column": "df_<table>['<col>']  // or a short description",
      "filter": "<a one-line pandas-style filter expression>",
      "reason": "<one sentence grounding it in the schema values>",
      "ambiguity": "low"
    }},
    ...
  ]
}}

AMBIGUITY RATING (used downstream to decide whether a heavier planner
should fire — be honest, this is NOT a confidence score for YOU):
  "low"    — the phrase maps to ONE obvious column+value. No reasonable
             alternative interpretation exists. Example: "total ARR" on
             a schema with df_customers['arr_inr_lakhs'].
  "medium" — the phrase could map to 2 different filter sketches but one
             is clearly preferred (by policy fact, verb, or
             column-direct-match). Example: "senior staff" on a corpus
             where IT_Asset says L4+ and Salary says L5+ — clear by verb
             but still ambiguous in isolation.
  "high"   — the phrase has MULTIPLE equally-plausible interpretations
             that would yield MATERIALLY DIFFERENT row sets. Example:
             "haven't bothered with certifications" (zero completed vs
             pending/overdue), or "flagged" on a corpus with both
             vendor risk_status and a separate hr_flagged column.

Default to "low" when in doubt. Only mark "high" when you genuinely
cannot pick a winner by yourself — in which case the planner will.

If the question needs NO resolution (all terms are already concrete),
return {{"resolutions": []}}.
"""


async def resolve_query_terms(
    *,
    query: str,
    dfs: dict[str, pd.DataFrame],
    today_iso: str,
    policy_facts_block: str = "",
) -> list[dict[str, str]]:
    """Run the resolver pass. Returns a list of resolution dicts, each
    with `phrase`, `column`, `filter`, `reason`. Best-effort — any
    failure returns [].

    `policy_facts_block` is the pre-formatted string from
    `fact_extractor.format_facts_for_prompt()` — passing it in lets the
    resolver disambiguate words like "senior" against the PDF rule whose
    VERB matches the query's verb (laptop → IT_Asset's "L4+", not
    Salary_Structure's "L5+").
    """
    if not dfs:
        return []
    schema_preview = _build_schema_preview(dfs)
    pf = policy_facts_block.strip() or "(no policy facts retrieved for this query)"
    prompt = (
        _RESOLVER_PROMPT
        .replace("{today}", today_iso)
        .replace("{schema_preview}", schema_preview)
        .replace("{policy_facts}", pf)
        .replace("{query}", query)
    )
    try:
        raw = await _complete_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=1500, temperature=0.0,
        )
    except Exception:
        return []

    stripped = _strip_json_fence(raw or "")
    try:
        parsed = json.loads(stripped)
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    rules = parsed.get("resolutions") or []
    if not isinstance(rules, list):
        return []
    out: list[dict[str, str]] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        phrase = str(r.get("phrase") or "").strip()
        flt = str(r.get("filter") or "").strip()
        if not phrase or not flt:
            continue
        amb = str(r.get("ambiguity", "low")).strip().lower()
        if amb not in ("low", "medium", "high"):
            amb = "low"
        out.append({
            "phrase": phrase[:120],
            "column": str(r.get("column") or "").strip()[:120],
            "filter": flt[:300],
            "reason": str(r.get("reason") or "").strip()[:300],
            "ambiguity": amb,
        })
    return out


def _strip_json_fence(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    a = s.find("{")
    b = s.rfind("}")
    if a >= 0 and b > a:
        return s[a : b + 1]
    return s


def format_resolutions_for_prompt(rules: list[dict[str, str]]) -> str:
    """Render the resolutions as a prompt-ready section the code-gen
    step can copy filter expressions from directly."""
    if not rules:
        return ""
    lines: list[str] = [
        "=== USER-INTENT RESOLUTIONS (grounded in this corpus's actual values) ===",
        "These are the phrases from the question, mapped to concrete filters",
        "against columns + values that exist in THIS dataset. Use these",
        "filter expressions verbatim when writing the final code — they are",
        "guaranteed to reference real columns, not invented ones.",
        "",
    ]
    for r in rules:
        lines.append(f"  • \"{r['phrase']}\"")
        if r.get("column"):
            lines.append(f"      column: {r['column']}")
        lines.append(f"      filter: {r['filter']}")
        if r.get("reason"):
            lines.append(f"      why:    {r['reason']}")
        lines.append("")
    return "\n".join(lines)
