# OOD harness — findings log

Append-only. One entry per architectural issue the OOD harness surfaces.
Entries here drive the research roadmap.

---

## Finding 1 — analytics routing ignores `doc_ids` scope

**Date:** 2026-04-22 (night OOD-1)
**Status:** diagnosed, fix pending (tracked as "A" in session plan)
**Discovered via:** code_docs domain smoke test, 5 queries × 1 run

**Observation.** When a user uploads non-tabular docs (FastAPI tutorial markdown)
AND the workspace already has tabular docs anywhere (TechNova `.xlsx` files),
analytics routing fires on every query regardless of the `req.doc_ids` scope the
caller passed. Result: a question about FastAPI gets executed as a multi-table
analytics query against the TechNova tables.

Evidence from baseline `ood_preA_v2_1776869170.json`:
- Query: "What Python class does FastAPI recommend for predefined path params?"
- `doc_ids=[35ce94fec643, a9682e99e235]` (the two FastAPI markdown files)
- Response:
  ```
  "answer_mode": "analytics",
  "tables_joined": ["departments", "employees", "salary_records", ...11 TechNova tables],
  "filename": "00_README_and_Schema.xlsx + 01_Departments.xlsx + ..."
  ```

**Root cause.** [chat.py:1792](../backend/src/api/routers/chat.py#L1792):

```python
if _is_analytics_followup or _is_multi_table(req.query, _tabular_count):
```

`_tabular_count` is the **global** count of tabular docs visible to the user,
not scoped to `req.doc_ids`. `is_multi_table_query(query, tabular_doc_count)`
at [analytics_agent.py:1732](../backend/src/pipelines/analytics_agent.py#L1732)
returns True unconditionally when `tabular_doc_count >= 3`. With the TechNova
corpus loaded (11+ tabular docs), the threshold is always exceeded, so every
query routes to analytics regardless of actual query type.

**Why TechNova golden harness never caught this.** In that harness the user
actually has the TechNova tables AND every query is genuinely a multi-table
question. The broken routing is correct in that universe by coincidence. The
bug is invisible without an OOD corpus.

**Replication CONFIRMED (2026-04-23 morning).** Scientific domain (arXiv
survey `2404.14294`, 36-page PDF) — all 5 queries routed to
`answer_mode: "analytics"` with the same 11 TechNova tables loaded.
Baseline: `ood_scientific_preA_1776870297.json`. 4/5 passing.
Not code-docs-specific. Bug is corpus-agnostic.

**Proposed fix scope.** `_is_multi_table` should receive a `tabular_doc_count`
computed from `req.doc_ids` when `doc_ids` is non-empty. When a caller scopes
to a non-tabular doc set, analytics routing must bypass and fall through to
the pure-RAG path. Ship behind flag, measure pre/post on OOD harness, require
TechNova golden harness stays at 9/20.

**Tangential note — T5 did NOT hallucinate.** The same baseline shows the
system cleanly did not invent a "FastAPI 2.0 release date" — no date, year,
or version string in the answer content. The 0% hallucination property held
under OOD conditions. This is the system's current crown jewel and survives
the routing bug.

---

## Finding 1a — architectural correctness ≠ answer-match; route assertion is required

**Date:** 2026-04-23 morning (surfaced during Finding 1 replication check;
  renamed from 1b → 1a because it **precedes** Finding 1 in importance —
  it's the reason Finding 1 was invisible until now)
**Status:** scorer fix pending (bundled into Finding 2 patch)

Despite routing all OOD queries to the analytics agent with 11 TechNova tables
loaded into scope, the system has been producing *mostly-correct* answers on
OOD content. Sample from scientific baseline:
- T1 "LLaMA-2-70B params" → `result: '70.0'` (correct)
- T2 GPU comparison → synthesized table with `estimated_model_memory_gb`,
  `rtx_3090ti_gpus_required`, `a100_vram_gb_each` (correct comparison)
- T4 VRAM math → `{'model': 'LLaMA-2-70B', 'weights_vram_gb': 140,
  'gpu_type': 'NVIDIA A100', 'vram_per_gpu_gb': 80, 'min_gpus_needed': 2}`
  (full structured derivation)

**Mechanism.** The analytics agent receives:
1. The 11 TechNova table schemas (from wrong routing)
2. The POLICY FACTS block from the Phase 1 fact extractor, which DOES include
   facts from the newly-uploaded PDF (because fact extraction runs on upload)
3. The user's question

It then synthesizes answers from #2 + LLM reasoning, largely ignoring #1 when
#1 is irrelevant. The TechNova tables are loaded but unused.

**The masking is structural, not incidental.** The fact index accidentally
answers OOD queries when the routing bug misroutes them to TechNova analytics.
This means architectural "correctness" can't be measured just by *"did the
answer come out right"* — it has to be measured by *"did the right code path
fire?"* The OOD harness needs a **route-assertion** check (assert
`answer_mode == expected_mode_for_this_domain` AND that `tables_joined` does
not contain foreign-corpus tables) in addition to answer-match — or A's
impact will be invisible in pure pass/fail terms.

**Scariest implication — applies to the TechNova golden harness too.** The
same masking mechanism means: we do not know how many of the 9/20 TechNova
golden-harness passes are architecturally right vs accidentally right via the
same fact-index synthesis. Until route assertion exists, that number is
architecturally ambiguous.

**Why route assertion must land with the scorer patch, not with A.** If A
ships without route assertion, A might look identical on pass/fail numbers.
TechNova docs are uploaded, fact index pulls the right answer, user never
knows the routing is still broken (or still right — either way invisible).
Route assertion is how you PROVE A actually did something.

**Why this matters (operational).**
- Good: the system has been *behaviorally* resilient on OOD — users getting
  sensible answers despite wrong plumbing.
- Bad: the resilience is accidental. Any prompt tweak or model change that
  makes the analytics agent *trust* the loaded tables more will flip this from
  "surprisingly right" to "catastrophically wrong."
- Fixing A (proper routing) will make the behavior predictable — pure-RAG
  path on non-tabular scope instead of analytics-agent-on-facts-only.

**Action:** add route-assertion to the scorer now (Finding 2 fix #3). Do not
ship A until the harness can prove A changed the code path, not just the
answer.

---

## Finding 2 — OOD scorer has three gaps that bias results

**Date:** 2026-04-23 morning
**Status:** FIXED (2026-04-23, same day). 3-fix patch landed in `ood_eval.py`.
**Budget used:** ~50 min

**Gap 1 — numeric substring false positive.**
T3 ("how many top-level optimization categories?") system returned
`{'top_level_optimization_categories': 8}` (WRONG — correct is 3). My scorer
passed it because `"3"` appears elsewhere in the serialized blob (metadata,
other numbers). Substring matching on short numeric strings is too loose.

**Fix 1:** for `scalar_checks`, match the expected value against
`analytics.result` specifically (scalar or dict value, hint-guided), NOT the
full serialized blob. Reject if the result-level value doesn't match.

**Gap 2 — structural abstention missed.**
T5 ("learning rate recommendation?") system returned
`{'answer': None, 'context': 'The available uploaded paper facts cover
inference efficiency taxonomy and hardware requirements...'}`. This is honest
abstention — the system knows what it has and what it doesn't. But my phrase
list checked for string patterns like "not covered", "I don't have" — missed
the `answer: None` structural form.

**Fix 2:** add a structural abstention check — if `analytics.result` is None,
or `analytics.result` is a dict with `answer: null` + a "context" that
indicates bounds, count as abstention. Phrase check and structural check
compose as OR (either form passes).

**Gap 3 — no route assertion (see Finding 1a).**
Queries on non-tabular domains (code_docs, scientific) should NOT route to
`answer_mode: "analytics"` with foreign-corpus `tables_joined`. Currently
they do, and the scorer didn't notice — because it only checks the
answer, not the path.

**Fix 3:** every query evaluates an additional route-assertion check. The
domain spec declares `forbidden_routes` (e.g. `["analytics"]` for non-tabular
OOD domains). A query passes only if:
  (a) answer match succeeds AND
  (b) `answer_mode` is not in `forbidden_routes`
Record the actual `answer_mode` and the first ~5 entries of `tables_joined`
in the QueryReport for diagnostic visibility.

**Scope:** scorer-only patch. Ground truth unchanged. This is bug-in-the-ruler
territory — not "loosening to rescue." It's making the scorer actually measure
what it claims to measure, including the architectural path the answer came
through.

**Post-patch baseline (2026-04-23, `ood_postScorer_1776871573.json`).**
With the fixed scorer running against the *current* (pre-A) backend:

| domain | answer-match (old scorer) | route-ok + answer-match (new scorer) |
|---|---|---|
| code_docs | 2/5 | **0/5** |
| scientific | 4/5 | **0/5** |
| overall | 6/10 | **0/10** |

Every query routes to `answer_mode='analytics'` with the 11 TechNova tables
joined. Route assertion fails all 10, regardless of answer match. This is
the honest pre-A floor. When A ships and routes non-tabular scopes away
from analytics, the delta from 0/10 is real measurement of A's impact.

Sub-findings the scorer fixes surfaced:
- SCIENTIFIC_3 previously `result=8` (wrong) "passed" via old-scorer blob
  substring hit on `"3"`. New run shows `result=3` (correct) — but this
  is LLM run-to-run variance at the analytics-agent level, not a bug fix.
  Route is still wrong in both cases.
- SCIENTIFIC_5 structural abstention (`analytics.result.answer is
  explicitly None`) now passes the phrase-check gate via structural path.
  Exactly the Gap 2 case.
- CODE_DOCS_3 `benefits_of_using_python_type_declarations_in_recap=4`
  correctly resolved via hint-match in dict result, not blob substring.
  Gap 1 case.

