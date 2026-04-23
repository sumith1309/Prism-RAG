# Schema Profiler — U1a Design

**Goal.** Replace TechNova-shaped hardcoded mappings with a runtime profiler
that recovers the same information from any uploaded corpus — so the system
works on hospital data, legal contracts, retail sales without per-corpus
config changes.

**Ship criterion for U1a.** Golden 3×20 holds at ≥ 8/20 meeting CI (same
noise band as post-B `post_B_golden.json`). Q1 per-query threshold unchanged.
OOD holds at ≥ 8/10. If golden drops, profiler under-extracts; if OOD drops,
profiler broke the grounded path.

**Flag.** `PRISM_DYNAMIC_PROFILER=1`. Default off during rollout. Same
discipline as `PRISM_PLANNER` and `PRISM_SCOPED_ANALYTICS_ROUTING`.

---

## TechNova-ism audit (what we're replacing)

### `analytics_agent.py` — prompt block for multi-table agent

| Lines | Block | Classification |
|---|---|---|
| 1145–1212 | **BUSINESS-TERM → FILTER TRANSLATION** | Hardcoded: "engineers" → `'Engineering'`, "biggest accounts" → `'Tier 1'`, "serious incidents" → `('SEV-1','SEV-2')`, "haven't X" → `~df.isin()`, "external certifications" → explicit list (AWS/Azure/CKA/...), "retention bonus" → `0.30 × total_ctc_inr_lakhs`, "compliance flagged" → `rate < 0.90` |
| 1213–1228 | **GEO / MARKET GLOSSARY** | Hardcoded: "APAC" → explicit country list; "regulated Asian markets" → India/Japan/S.Korea |
| 1230–1270 | **TECHNOVA CORPUS CONSTANTS** | Fully hardcoded facts: retention ceiling 30%, ESOP threshold L5+, on-call rates ₹5000/₹2500, compliance threshold 90%, cert bonus ₹25k, AI cluster = 16 × A100, Q4 utilization 94.7%, L4+ MacBook policy, etc. |
| 1272–1286 | **TABLE SEMANTICS** | Corpus-specific: `df_assets_licenses` shape, `df_training_compliance` status enum, vendor names (Apple, NVIDIA, AWS) |
| 1287–~1600 | **Pattern A–I examples** | Operations themselves are generic (merge, dedupe, anti-join, ranking). Example code uses TechNova column names (`df_customers`, `tier`, `vendor_name`). |
| 1488 | `TECH_DEPTS = ['Engineering', ...]` | Hardcoded list embedded inside a Pattern example. |

### `fact_extractor.py`

| Lines | Content | Classification |
|---|---|---|
| 53–57 | Few-shot examples in prompt | Corpus-specific: "Engineering utilized 94.7%", "on-call stipend ₹5000", "FY25-26 GPU compute ₹133.99 Cr". These bias the LLM toward policy-PDF extraction. |
| 91–103 | `_has_rule_shaped_content` pre-filter regex | Currency tokens biased toward INR/rupees; threshold verbs biased toward enterprise-policy language; `l[1-9]` and `tier\s+[0-9]` match hardcoded TechNova ladders. |

### `term_resolver.py`

| Content | Classification |
|---|---|
| Few-shot examples in the prompt (lines ~200–250) | "biggest accounts" → tier 1; "senior staff" → level column; "flagged vendors" → risk/status; "without ESOPs" → level ≥ L5. These are GUIDANCE examples, not static filters — but they shape the LLM's interpretation priors. |
| Actual function body | Already schema-aware — inspects real column values at query time. Only the prompt's few-shot block is TechNova-shaped. |

### `core/store.py` + upload path

Nothing TechNova-specific in the storage layer. Profiler output gets a
new SQLModel table — clean add.

---

## Profiler module — interface + responsibilities

### Module: `backend/src/pipelines/schema_profiler.py` (new)

Public API:

```python
def profile_table(df: pd.DataFrame, filename: str) -> TableProfile:
    """Deterministic profile of a single tabular file. Pure function."""

def profile_corpus(tables: list[tuple[str, pd.DataFrame]]) -> CorpusProfile:
    """Profile N tables, infer FK candidates, build cross-table summary."""

def format_profile_for_prompt(profile: CorpusProfile) -> str:
    """Render profile as a schema block the LLM can read — replacing the
    static TECHNOVA CORPUS CONSTANTS + BUSINESS-TERM + TABLE SEMANTICS
    blocks in analytics_agent.py."""
```

### `TableProfile` shape

```json
{
  "table_id": "df_customers",
  "filename": "04_Customers.xlsx",
  "row_count": 500,
  "columns": [
    {
      "name": "tier",
      "dtype": "categorical",
      "unique_count": 3,
      "unique_values": ["Tier 1", "Tier 2", "Tier 3"],
      "top_frequencies": {"Tier 2": 240, "Tier 3": 180, "Tier 1": 80},
      "null_rate": 0.0,
      "role_hints": ["segmentation", "orderable-by-name"],
      "business_term_candidates": ["tier", "segment", "size"]
    },
    {
      "name": "arr_inr_lakhs",
      "dtype": "numeric",
      "min": 1.2, "median": 14.5, "max": 89.3, "mean": 18.2,
      "unit_inferred": "INR_lakhs",
      "null_rate": 0.0,
      "role_hints": ["monetary", "orderable"],
      "business_term_candidates": ["arr", "revenue", "amount", "value"]
    },
    {
      "name": "customer_id",
      "dtype": "id",
      "unique_count": 500,
      "null_rate": 0.0,
      "role_hints": ["primary_key_candidate"],
      "business_term_candidates": ["id", "customer"]
    }
  ]
}
```

### `CorpusProfile` shape

```json
{
  "table_count": 11,
  "tables": [ TableProfile, ... ],
  "foreign_keys": [
    {
      "from_table": "df_incidents",
      "from_col": "customer_id",
      "to_table": "df_customers",
      "to_col": "customer_id",
      "overlap_pct": 0.94,
      "confidence": "high"
    }
  ],
  "unit_dictionary": { "INR_lakhs": ["arr_inr_lakhs", "total_ctc_inr_lakhs"], "INR_crores": ["budget_inr_crores"] },
  "created_at": "2026-04-24T..."
}
```

### Column-type inference rules (deterministic, no LLM)

- `id`: unique_count == row_count AND name ends in `_id` / `_key` / `id`
- `categorical`: unique_count ≤ min(20, row_count × 0.1) AND dtype is object/string
- `numeric`: pandas numeric dtype, stats reported (min/median/max/mean)
- `datetime`: pandas datetime OR parseable date strings
- `text`: object/string dtype not fitting `id` or `categorical`
- `boolean`: only two unique values, one of: {True/False, yes/no, y/n, 0/1}

### Foreign-key inference

Two signals, both required for "high" confidence:
1. **Name match**: `from_col` matches a PK candidate in another table by name
   (e.g. `df_a.customer_id` ↔ `df_customers.customer_id`)
2. **Value overlap**: ≥ 80% of non-null values in `from_col` exist in `to_col`

Medium confidence: name match OR value overlap ≥ 95%. Low: exact value
overlap ≥ 50% without name match (rare enough to surface but not trust).

### Unit inference

Suffix patterns on numeric columns:
- `_inr_lakhs`, `_inr_crores`, `_inr`, `_usd`, `_eur` → currency
- `_pct`, `_percent`, `_rate`, `ratio` → percentage (with min/max check: 0–1 or 0–100)
- `_days`, `_weeks`, `_months`, `_years`, `_hours` → duration
- `_count`, `num_`, `n_`, `count_of_` → count
- No match → unit unknown, still report stats

### Business-term candidates

Derived from column name tokens (split on `_`, lowercase, stem):

- `arr_inr_lakhs` → `{arr, revenue, amount, lakhs}`
- `department_name` → `{department, name, dept}`
- `risk_status` → `{risk, status, flag, flagged}`

This is the replacement for the static Business-Term Glossary block. At
query time, the term resolver searches *actual column term candidates*
instead of looking up hardcoded phrases.

---

## Integration — how each consumer changes

### 1. Upload hook (`embedding_pipeline.ingest_file`)

After fact extraction, call profiler for tabular docs:

```python
if ext in {".xlsx", ".xls", ".csv"}:
    df = load_tabular(file_path)
    profile = profile_table(df, filename)
    store.save_table_profile(doc_id, profile)
```

Flag-guarded so existing uploads keep working without profiler data.

### 2. Query time (`analytics_agent.py`)

```python
if profiler_enabled():
    corpus_profile = profile_corpus([(name, df) for name, df in loaded_tables.items()])
    schema_block = format_profile_for_prompt(corpus_profile)
    # Render schema_block into MULTI_TABLE_ANALYTICS_PROMPT in place of:
    #   TECHNOVA CORPUS CONSTANTS block (lines 1230–1270)
    #   BUSINESS-TERM → FILTER TRANSLATION block (lines 1145–1212)
    #   TABLE SEMANTICS block (lines 1272–1286)
else:
    schema_block = _STATIC_TECHNOVA_BLOCKS  # preserved for rollback
```

### 3. `fact_extractor.py`

- Pre-filter `_has_rule_shaped_content` kept (it's a cost-saver, no TechNova
  bias in the general shapes). Drop the `tier\s+[0-9]` and `l[1-9]` patterns
  — those are TechNova ladders. Replace with generic "level X" / "grade X"
  patterns IF they appear; otherwise let the LLM handle.
- Few-shot examples in the LLM prompt: replace TechNova specifics with
  domain-neutral examples (hospital, retail, legal — short stubs).

### 4. `term_resolver.py`

- Few-shot examples: keep the STRUCTURE ("phrase → column → filter expression")
  but use domain-neutral examples. The function is already schema-aware;
  only the prompt needs the TechNova-ism removal.

---

## Pattern A–I treatment

Patterns themselves are **operations**: anti-join, dedupe-after-merge,
aggregate-before-rank, cross-sheet summary, etc. These are universally
valid RAG/pandas patterns. Keep them.

Example code in each pattern currently uses TechNova column names
(`df_customers`, `tier`, `vendor_name`). U1a changes this to generic
column names (`df_a`, `df_b`, `dim_col`, `measure_col`) — the LLM reads
the pattern as a *template*, then applies it to the corpus it has.

No deletion of patterns. Just abstraction of the examples.

---

## Implementation order (for the follow-up code ship)

1. **schema_profiler.py** — pure functions, no deps on store or LLM. Unit-testable standalone on synthetic DataFrames.
2. **CorpusProfile storage** — new SQLModel table + CRUD in `core/store.py`.
3. **Upload hook** — wire profile save into `embedding_pipeline.ingest_file`.
4. **format_profile_for_prompt** — the rendering function. Design choice: single concatenated schema block, same structure as existing TABLE SEMANTICS but populated from profile.
5. **analytics_agent.py refactor** — introduce `_render_schema_block(corpus_profile)`; prompt uses it when flag is on.
6. **fact_extractor.py** — narrow the few-shot examples + relax the pre-filter.
7. **term_resolver.py** — narrow the few-shot examples.
8. **Golden harness re-run** — 3×20, flag on. Must hit ≥ 8/20. Q1 still at require_pass=2.
9. **OOD harness re-run** — must hit ≥ 8/10. Route + source assertions still pass.

Each step commits independently. Ship atomically at the end with both
baselines as evidence. Same discipline as A + B.

---

## Out of scope for U1a (deferred)

- **U1b**: Running against a second corpus. Needs dataset sourcing.
- **U1c**: Running against 3 corpora. Needs two more.
- **Value-distribution inspection for dynamic glossary**: e.g. "senior"
  inferred from level-column value distribution. Works out of the box
  via the existing term_resolver; profiler just feeds it better data.
  Extending the resolver to use distribution statistics (not just
  unique values) is U1a-adjacent work — do it only if golden drops.
- **Dropping TECH_DEPTS list at line 1488**: embedded inside Pattern
  example. Will be replaced when patterns are abstracted.
- **GEO / MARKET GLOSSARY**: kept as-is for now. It's fact-like
  knowledge (APAC countries) that doesn't belong to any specific
  corpus. Could move to a general-knowledge resource later; not U1a.
