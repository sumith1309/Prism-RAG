# Q3 pre-Phase-3 variance capture (2026-04-22)

## Purpose

Frozen record of the one-shot code-gen's behaviour on Q3 (IPO regulated-Asian
accounts) BEFORE the ReAct planner lands. This captures why the query is
flaky and serves as the Phase 3 success criterion.

## What's here

Ten Python files — `Q3_run01.py` through `Q3_run10.py` — each the full pandas
code the LLM generated for the identical prompt, captured by
`rag_golden_eval.py --only Q3 --runs 10 --log-code`.

Header of each file records pass/fail and latency. Identical query. Different
code. Three passed, seven failed with zero rows.

## The single decision that split the runs

All 10 runs correctly filtered to:
- Tier 1 customers in {Japan, India, South Korea}
- Account manager level below L5 (no ESOPs)

All 10 diverged on interpreting **"haven't bothered with any certifications"**:

### Interpretation A — PASS (3/10)

"Haven't bothered" = has zero completed external certifications.

```python
certified_emp_ids = {
    e for e in df_training_compliance
    if module_name ∈ external-cert set AND status == 'Completed'
}
result = no_esop[~isin(certified_emp_ids)]   # anti-join
```

Correct. Rohit Jain + Kiran Malhotra have zero external-cert records at all,
so they're not in `certified_emp_ids`, so they pass `~isin`. Two rows returned.

Seen in: run02, run04, run05.

### Interpretation B — FAIL (7/10)

"Haven't bothered" = has at least one non-completed external cert row
(pending / overdue / in-progress).

```python
uncertified_records = training[
    module_name ∈ external-cert AND status != 'Completed'
]
result = no_esop[isin(uncertified_records.employee_id)]   # direct join
```

Wrong. Rohit/Kiran have NO external-cert rows at all — not completed, not
pending. They fail `isin`. Zero rows returned.

Seen in: run01, run03, run06, run07, run08, run09, run10.

## Why this matters for Phase 3

Planner must decompose the phrase into a sub-decision, surface both
interpretations, and use a dry-check ("would either produce an empty result
against the rest of the filters? does one match the user's likely intent?")
before generating the final code.

## Success criterion for Phase 3

Re-run the exact same capture after Phase 3 ships:

```bash
rm -rf /tmp/q3_post_phase3 && \
backend/.venv/bin/python rag_golden_eval.py \
  --only Q3 --runs 10 --log-code /tmp/q3_post_phase3
```

Target: 10/10 passes, and all 10 code files use Interpretation A
(the anti-join on `~isin(certified_emp_ids)`). No interpretation B.

If 10/10 pass but some runs still use interpretation B accidentally,
that's a lucky coincidence (Rohit/Kiran might have the right answer anyway
due to data happenstance) — inspect the generated code directly.
