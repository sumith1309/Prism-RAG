# OOD Harness — out-of-distribution RAG evaluation

## Why this exists

The current golden harness (`../golden_queries.json`) measures 20 queries on a single
corpus (TechNova — 11 policy PDFs + 11 tables). Scoring 100% on it does NOT prove
the system generalizes to arbitrary uploads + arbitrary questions. This harness
tests exactly that.

## Methodology

**8 domains × 5 documents × 5 queries = 200 query runs at full scale.**
Start smaller: seed each domain with 1 document + 5 queries = 40 queries total.
Grow the harness as we learn which domains break the system.

Each domain gets its own isolated tenant (one workspace per domain) to prevent
cross-corpus retrieval contamination. After baseline-per-domain is stable, we add
a "mixed corpus" tenant where all docs live together — this tests whether the
system correctly routes queries to the right docs.

## Query difficulty ladder (required for each domain)

Each domain has exactly 5 queries, one per difficulty tier:

1. **Extraction** — single fact lookup ("What was the trial end date?")
2. **Comparison** — compare 2+ facts ("Which drug had higher response rate?")
3. **Aggregation** — sum/count/average ("Total revenue across quarters?")
4. **Multi-step reasoning** — chain of 2-3 derivations ("Rate × period × headcount?")
5. **Abstention** — answer is NOT in the corpus ("What was the 2050 forecast?")

Tier 5 (abstention) is NON-NEGOTIABLE. It tests the 0% hallucination property
under adversarial conditions. If tier 5 fails, the system is hallucinating on
domain it wasn't trained on — the most important failure to catch.

## Scoring rules

- **Strict** — exact numeric match within tolerance (same as golden_queries.json)
- **Abstention** — tier-5 queries pass if system correctly says "I don't know /
  not in corpus." Fail if it invents an answer.
- **Per-domain score** — X/5 per domain, then aggregated
- **Overall OOD score** — sum-across-domains / 40 (or /200 at full scale)

## Baselines to capture

- `ood_baseline_preA.json` — current system (post-Phase-3, nothing changed)
- `ood_baseline_postA.json` — after hybrid retrieval upgrade
- `ood_baseline_postB.json` — after real ReAct multi-step loop
- `ood_baseline_postC.json` — after dynamic domain adaptation

Each step ships ONLY if OOD delta > 0 AND TechNova golden harness doesn't regress.

## Explicitly not in scope

- Images, charts, scanned PDFs (OCR is a separate subsystem)
- Audio/video transcription
- Real-time data (stock tickers, weather)
- Queries requiring external web search

These are valid limitations to declare up-front, not hallucinate around.

## Next action (owned by user)

See `domain_list.md` for the 8 domains + sourcing notes + query templates.
Populate ONE domain first as a template. Once it runs end-to-end, the remaining
7 are mechanical.
