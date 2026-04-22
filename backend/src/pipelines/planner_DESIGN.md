# Phase 3 — ReAct Planner Design

_Design-only document. Implementation lives in `planner.py` (tbd)._

## Problem this solves

Current one-shot code-gen has structural non-determinism on ambiguous
business phrases. Evidence from Q3 capture
(`q3_pre_phase3_capture/README.md`): 10 runs of the same query produced
two semantically-different filter shapes for "haven't bothered with any
certifications" — interpretation A (PASS 3/10) vs interpretation B
(FAIL 7/10). The current prompt can't force the LLM to pick consistently
because the ambiguity is genuinely in the user's phrase.

## Solution: explicit decomposition before code-gen

Replace one LLM call ("write pandas for this question") with a pipeline:

```
        user query
           │
           ▼
    ┌───────────────────────────┐
    │  1. PLAN  (LLM #1)         │  Enumerate sub-decisions; for each
    │  Output: PlanSpec JSON     │  ambiguous phrase, propose 1-N
    └──────────┬────────────────┘  interpretations with filter sketches
               │
               ▼
    ┌───────────────────────────┐
    │  2. VERIFY  (mechanical)   │  Dry-run each proposed filter against
    │  Output: ResolvedPlan      │  the data. Reject dead-ends (0 rows
    └──────────┬────────────────┘  from over-restrictive filters). Pick
               │                     most-likely-intent that survives.
               ▼
    ┌───────────────────────────┐
    │  3. CODE-GEN  (LLM #2)     │  Write final pandas using RESOLVED
    │  Output: pandas code       │  filters — no ambiguity left.
    └──────────┬────────────────┘
               │
               ▼
    ┌───────────────────────────┐
    │  4. EXECUTE  (sandbox)     │
    └──────────┬────────────────┘
               │
               ▼
    ┌───────────────────────────┐
    │  5. VALIDATE  (LLM #3)     │  Same as today. Sanity-check result
    │  Output: OK | CONCERN:...  │  shape / magnitude.
    └──────────┬────────────────┘
               │ (if CONCERN)
               ▼
    ┌───────────────────────────┐
    │  6. RETRY-WITH-CONCERN     │  Feed concern back into PLAN stage
    │  (loop back to step 1)     │  (max 1-2 retries). Concern becomes
    └───────────────────────────┘  an explicit sub-decision to resolve.
```

Latency cost: ~4-5 LLM calls per query (vs 2 today) → ~30-45s.
Accuracy win: eliminates interpretation variance.

## Data structures

```python
@dataclass
class Interpretation:
    """One way to resolve an ambiguous phrase."""
    id: str                           # "D1.A", "D1.B"
    description: str                  # "Zero completed external-cert rows"
    filter_sketch: str                # pandas-style expr for CODE-GEN
    required_tables: list[str]        # ["training_compliance", "employees"]
    required_columns: list[str]       # ["training_compliance.status", ...]

@dataclass
class SubDecision:
    """An ambiguous phrase in the query + candidate interpretations."""
    id: str                           # "D1"
    phrase: str                       # "haven't bothered with any certifications"
    interpretations: list[Interpretation]
    likely_intent: str                # "D1.A"
    reasoning: str                    # why A over B in user's intent

@dataclass
class PlanSpec:
    """Full decomposition of a query."""
    sub_decisions: list[SubDecision]
    unambiguous_filters: list[str]    # filter sketches with no ambiguity
    missing_data_dimensions: list[str] # e.g. "corpus lacks temporal series of licensed_seats"
    proceed: bool                     # false → return honest "cannot answer" instead of code-gen

@dataclass
class DryCheckResult:
    sub_decision_id: str
    interpretation_id: str
    sample_row_count: int             # how many rows this filter would keep (on sample)
    full_row_count: int | None        # if cheap enough to run on full data
    empty_cascade: bool               # True if this + other filters ⇒ 0 rows
    notes: str

@dataclass
class ResolvedPlan:
    """PlanSpec + dry-check results → chosen interpretations."""
    chosen: dict[str, str]            # sub_decision_id → interpretation_id
    all_filters: list[str]            # the filter sketches to use in code-gen
    fallback_explanation: str | None  # if plan cannot proceed, why not
```

## Prompts

### PLAN prompt (LLM #1)

```
You are a data analyst's PLANNER. You do NOT write code yet. Your job is
to decompose the question into concrete sub-decisions a code-gen step
can execute without ambiguity.

Given:
  - The question.
  - The loaded tables' schemas + sample values.
  - Retrieved policy facts from uploaded PDFs.

For each phrase that could have MULTIPLE reasonable interpretations
against this corpus, enumerate those interpretations. For each, propose
a filter sketch (pandas-style pseudo-code) and list the exact columns it
touches.

Then pick the MOST-LIKELY-INTENT for each ambiguous phrase and explain
why in one sentence, referencing the question's verb / context / any
matching policy fact.

If the corpus lacks a data dimension the question requires (e.g. the
user asks about "last 90 days" but no time-series exists), list it in
`missing_data_dimensions` AND set `proceed` to false. Do NOT fabricate
a proxy.

Output STRICT JSON conforming to PlanSpec above.
```

### CODE-GEN prompt (LLM #2)

Same as today's MULTI_TABLE_ANALYTICS_PROMPT, but the
term-resolutions block is replaced with the RESOLVED PLAN:

```
=== RESOLVED PLAN (use these filters verbatim) ===
  D1 "haven't bothered with any certifications"
     → chose interpretation A: zero completed external-cert rows
     → filter: employee_id NOT IN set(training_compliance[
         (module_name ∈ external-cert set) & (status == 'Completed')
       ].employee_id)
  D2 "biggest accounts"
     → chose: tier == 'Tier 1'
     → filter: customers[customers['tier'] == 'Tier 1']
  ...
```

Because the ambiguity is pre-resolved, CODE-GEN's variance collapses.

## Dry-check (mechanical, no LLM)

For each interpretation with a filter_sketch, compile a lightweight
pandas expr and run it against a SAMPLED copy of the loaded DataFrames
(e.g. first 200 rows of each). Record row counts.

Rejection rules:
- If a filter under the proposed plan (ALL filters AND'd) produces 0 rows
  on the full data, reject that interpretation and try the next one.
- If it produces an obviously absurd count (e.g. 100000 rows from
  10000-row inputs — a cartesian artifact), reject.

If ALL interpretations for a sub-decision fail dry-check, surface the
failure upstream: either retry PLAN with the dry-check feedback, or
return "cannot confidently answer" to the user.

## Retry-with-concern

When VALIDATE returns a CONCERN, the concern string becomes input to a
new PLAN round. The planner's prompt is augmented with:

```
PREVIOUS ATTEMPT FAILED VALIDATION:
  concern: {concern_string}
  chosen interpretations: D1.A, D2.B, ...
  result summary: {compact snippet of what was returned}

Propose a plan that addresses the concern. Different interpretations,
different tables, or honest "cannot answer" if the concern identifies
missing data.
```

Max 2 retries. After that, return the best attempt + visible concern
chip (current behaviour).

## Integration points

- New file: `backend/src/pipelines/planner.py`
- Modify: `analytics_agent.py::run_multi_table_query` — replace
  term_resolver + code-gen with plan → verify → code-gen
- Keep the policy-fact retrieval from Phase 1 (it's input to PLAN)
- Keep the cycle-safe scrubber + validator from Phase 2

## Success criteria (measured by harness)

Pre-Phase 3 (today's baseline, 3 runs × 20 queries):
- meeting CI: ~X/20 (from background task — TBD)
- Q3 variance: 3/10 passes, 2 interpretations

Post-Phase 3 targets (3 runs × 20 queries):
- meeting CI: ≥ 17/20 (stable-pass)
- Q3 re-capture (10 runs): 10/10 correct row count AND ≥ 9/10 using
  interpretation A. Pre-decided, NOT rationalized after the fact:
  * 10/10 correct + 10/10 interpretation A → pristine pass
  * 10/10 correct + 9/10 interpretation A → **SHIP IT**. Planner's job
    is variance reduction, not variance elimination. An occasional
    lucky-correct interpretation B doesn't break anything.
  * 10/10 correct + ≤ 8/10 interpretation A → investigate: either the
    planner is indifferent between interpretations (tighten prompt)
    or interpretation B's happy-path coincidence is noise.
  * < 10/10 correct → Phase 3 failed on its primary test case.
    Debug, do not ship.
- Expected-fails E6 + E7:
  - E6 passes → derived metric computed correctly
  - E7 RECOGNIZED as unanswerable → honest "no temporal series" response
    surfaced via `plan.proceed=false` + `missing_data_dimensions`

## Risks / known tradeoffs

1. **Latency**: 2-3x slower per query. Cache aggressively. Still faster than a wrong answer.
2. **Dry-check false positives**: overly-strict filter might pass dry-check (on small sample) but fail on full data. Mitigation: run full-data count on borderline cases.
3. **Planner confidence**: LLM might claim certainty on ambiguous phrases where both interpretations are equally valid. Mitigation: planner prompt requires `reasoning` field — human-reviewable post-hoc.
4. **Dead-loop**: retry-with-concern could loop if validator keeps objecting. Hard cap at 2 retries.
