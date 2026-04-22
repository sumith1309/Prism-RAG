"""Phase 3 — ReAct planner for analytics queries.

Replaces one-shot code-gen with:

    PLAN  (LLM)  →  VERIFY  (mechanical)  →  CODE-GEN  (LLM)  →  EXECUTE

PLAN decomposes the question into sub-decisions with candidate
interpretations. VERIFY dry-runs each on a sample to eliminate dead-ends.
CODE-GEN receives RESOLVED filters (zero ambiguity) and writes the final
pandas. EXECUTE is unchanged.

Design background: `planner_DESIGN.md`.
Bug report this addresses: `/q3_pre_phase3_capture/README.md`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.pipelines.generation_pipeline import _complete_chat


# ── Plan spec data structures ────────────────────────────────────────────

@dataclass
class Interpretation:
    id: str
    description: str
    filter_sketch: str
    required_tables: list[str] = field(default_factory=list)
    required_columns: list[str] = field(default_factory=list)


@dataclass
class PolicyFactBinding:
    """When a retrieved policy fact names specific values for this phrase,
    the planner MUST bind to those values. Server-side enforcement in
    dry_check_interpretations() rejects any chosen interpretation whose
    filter_sketch doesn't reference the bound values.
    """
    cited: bool = False
    source: str = ""                   # e.g. "Board_Minutes Q4 §5"
    values: list[str] = field(default_factory=list)  # e.g. ["Vietnam", "Indonesia"]


@dataclass
class SubDecision:
    id: str
    phrase: str
    interpretations: list[Interpretation]
    likely_intent: str
    reasoning: str
    policy_fact_binding: PolicyFactBinding = field(default_factory=PolicyFactBinding)


@dataclass
class PlanSpec:
    sub_decisions: list[SubDecision]
    unambiguous_filters: list[str]
    missing_data_dimensions: list[str]
    proceed: bool


@dataclass
class DryCheckResult:
    sub_decision_id: str
    interpretation_id: str
    full_row_count: int
    empty_cascade: bool
    notes: str


@dataclass
class ResolvedPlan:
    chosen: dict[str, str]              # sub_decision_id → interpretation_id
    all_filters: list[str]              # filter sketches for code-gen
    dry_check_log: list[DryCheckResult]
    fallback_explanation: str | None = None


# ── PLAN prompt ──────────────────────────────────────────────────────────

_PLAN_PROMPT = """You are a data analyst's PLANNER. You do NOT write code.
Your only job is to decompose the question into concrete sub-decisions a
code-gen step can execute without ambiguity.

TODAY: {today}. "last year" = calendar year today.year - 1.

{policy_facts}

SCHEMA (actual values from THIS corpus):
{schema_preview}

=== FOREIGN-KEY RELATIONSHIPS (use these to JOIN; do NOT claim missing) ===
{fk_list}

QUESTION:
{query}

INSTRUCTIONS:

1. DECOMPOSE CONSERVATIVELY. Only create a sub_decision for a phrase
   when MULTIPLE interpretations would yield MATERIALLY DIFFERENT filter
   values or row sets. If a phrase resolves to one clear column+value,
   put its filter sketch in `unambiguous_filters` directly — do NOT
   invent alternative interpretations just to populate the schema. A
   typical query has 1-3 sub_decisions, not 6-7.

2. For each truly ambiguous phrase, propose 2-4 interpretations. For each:
     - description: one short English sentence
     - filter_sketch: A SELF-CONTAINED, EVALUABLE pandas expression. It
       MUST reference ONLY df_<name> tables + pd/np. NO intermediate
       variables, NO pseudo-code, NO "team_completion_rate" or
       "training_by_employee" (those don't exist at the time the sketch
       runs). A downstream AST parser REJECTS sketches that reference
       unknown names — rejected sketches are dropped from the candidate
       pool, so writing pseudo-code = your interpretation is ignored.

       Wrong:  "team_completion_rate < 0.90"
               "training_by_employee[[...]]"
               "groupby(team)['status'].eq('Completed').any()"

       Right:  "df_training_compliance.merge(df_employees[['employee_id','department_id']], on='employee_id').groupby('department_id').apply(lambda g: (g['status']=='Completed').sum() / len(g) < 0.90)"
               "df_customers[df_customers['tier']=='Tier 1']"
               "df_vendors[df_vendors['risk_status'].isin(['Conditional','Suspended'])]"

       If the computation is too complex to fit in one self-contained
       expression, pick a NARROWER sub-decision that IS expressible,
       and leave the bigger computation to the code-gen step that
       follows.
     - required_tables: df_<name> tables the filter touches
     - required_columns: specific columns referenced

3. POLICY-FACT BINDING (STRUCTURAL — parsed server-side):
   For each sub_decision, fill in `policy_fact_binding`:
     - If a retrieved policy fact above NAMES SPECIFIC VALUES for this
       phrase (e.g. "Vietnam and Indonesia are data-localization risk",
       "mandatory modules are InfoSec/POSH/ABAC/DPDP", "ESOPs at L5+"),
       set cited=true, source=<fact source>, values=<exact values>.
       Your chosen interpretation MUST use those values — the server
       REJECTS any filter_sketch that doesn't reference them and
       overrides to the bound values.
     - If no policy fact names values for this phrase, set cited=false
       and leave source/values empty.

4. Pick the MOST-LIKELY-INTENT using:
     (a) the question's VERB and context
     (b) policy-fact binding values (these DOMINATE — if cited=true,
         pick the interpretation that uses those values)
     (c) common business sense (narrow > broad when in doubt)
   Write one-sentence `reasoning`.

5. WHEN TO SET proceed=false — high bar:
   Only set proceed=false if you can name which JOIN CHAIN fails. Cite:
     "Chain X.col1 → Y.col2 → Z.col3 is broken because <concrete column
      missing from FK list above>."
   Before setting proceed=false, walk the FK list. If the data can be
   reached via ANY chain of the listed foreign keys, proceed=true.
   Examples of ILLEGITIMATE proceed=false claims:
     - "No employee ID in training data" — FALSE if training_compliance.
       employee_id appears in the FK list or columns.
     - "No service-to-team linkage" — FALSE if products_services.
       owner_department_id and departments.department_id both exist.
     - "No service-to-vendor usage linkage" — FALSE if assets_licenses.
       vendor_id links through to services indirectly, or if vendors.
       owner_department_id aligns with service owner_department_id.

OUTPUT — STRICT JSON, no prose, no markdown fence, this shape:
{{
  "sub_decisions": [
    {{
      "id": "D1",
      "phrase": "...",
      "policy_fact_binding": {{
        "cited": true,
        "source": "Board_Minutes Q4 §5",
        "values": ["Vietnam", "Indonesia"]
      }},
      "interpretations": [
        {{
          "id": "D1.A",
          "description": "...",
          "filter_sketch": "df_customers[df_customers['country'].isin(['Vietnam','Indonesia'])]",
          "required_tables": ["df_customers"],
          "required_columns": ["country"]
        }}
      ],
      "likely_intent": "D1.A",
      "reasoning": "policy_fact_binding.cited=true forces these exact values"
    }}
  ],
  "unambiguous_filters": ["df_x['col'] == 'value'", ...],
  "missing_data_dimensions": [
    {{
      "dimension": "...",
      "explanation": "Chain X.col → Y.col is broken because Y lacks col (verified against FK list)."
    }}
  ],
  "proceed": true
}}

If proceed is false, sub_decisions and unambiguous_filters can be [].
"""


async def plan_query(
    *,
    query: str,
    schema_preview: str,
    policy_facts_block: str,
    today_iso: str,
    fk_list: str = "",
    previous_concern: str | None = None,
) -> PlanSpec:
    """Run the PLAN step. Returns a PlanSpec. If previous_concern is
    provided (retry-with-concern), it's appended to the prompt so the
    planner can propose different interpretations.

    `fk_list` is the rendered output of _detect_foreign_keys — included
    so the planner can't hallucinate "missing schema linkages" when the
    FK chain actually exists.
    """
    concern_block = ""
    if previous_concern:
        concern_block = (
            f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION:\n"
            f"  concern: {previous_concern}\n"
            f"Propose a plan that addresses the concern — different\n"
            f"interpretations, different tables, or set proceed=false\n"
            f"with an honest explanation if the concern reveals missing data."
        )

    prompt = (
        _PLAN_PROMPT
        .replace("{today}", today_iso)
        .replace("{policy_facts}", policy_facts_block.strip() or "(no policy facts retrieved)")
        .replace("{schema_preview}", schema_preview)
        .replace("{fk_list}", fk_list.strip() or "(no foreign keys auto-detected)")
        .replace("{query}", query)
        + concern_block
    )

    try:
        raw = await _complete_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=3000, temperature=0.0,
        )
    except Exception:
        return _empty_plan(proceed=True)

    cleaned = _strip_json_fence(raw or "")

    # Debug trace — when PRISM_PLANNER_DEBUG=1, dump the raw plan JSON
    # to a timestamped file in /tmp so we can inspect which interpretations
    # the planner picks for each query. Zero cost when flag is off.
    import os as _os
    if _os.environ.get("PRISM_PLANNER_DEBUG", "").strip() in ("1", "true", "yes"):
        try:
            import time as _time
            dbg_dir = _os.environ.get("PRISM_PLANNER_DEBUG_DIR", "/tmp/planner_debug")
            _os.makedirs(dbg_dir, exist_ok=True)
            ts = int(_time.time() * 1000)
            # Short query slug for filename readability
            slug = "".join(c if c.isalnum() else "_" for c in query[:40]).strip("_")
            dbg_path = f"{dbg_dir}/{ts}_{slug}.json"
            with open(dbg_path, "w") as f:
                f.write(cleaned)
            print(f"[planner-debug] plan dumped → {dbg_path}")
        except Exception:
            pass

    try:
        parsed = json.loads(cleaned)
    except Exception:
        return _empty_plan(proceed=True)
    if not isinstance(parsed, dict):
        return _empty_plan(proceed=True)

    return _parse_plan(parsed)


def _empty_plan(*, proceed: bool) -> PlanSpec:
    return PlanSpec(
        sub_decisions=[], unambiguous_filters=[],
        missing_data_dimensions=[], proceed=proceed,
    )


def _parse_plan(obj: dict[str, Any]) -> PlanSpec:
    sub_decisions: list[SubDecision] = []
    for raw_sd in obj.get("sub_decisions") or []:
        if not isinstance(raw_sd, dict):
            continue
        interps: list[Interpretation] = []
        for raw_i in raw_sd.get("interpretations") or []:
            if not isinstance(raw_i, dict):
                continue
            interps.append(Interpretation(
                id=str(raw_i.get("id") or "").strip(),
                description=str(raw_i.get("description") or "").strip()[:400],
                filter_sketch=str(raw_i.get("filter_sketch") or "").strip()[:500],
                required_tables=[str(t) for t in (raw_i.get("required_tables") or []) if t],
                required_columns=[str(c) for c in (raw_i.get("required_columns") or []) if c],
            ))
        if not interps:
            continue
        # Parse policy_fact_binding — enforced server-side in dry_check
        raw_binding = raw_sd.get("policy_fact_binding")
        binding = PolicyFactBinding()
        if isinstance(raw_binding, dict):
            binding = PolicyFactBinding(
                cited=bool(raw_binding.get("cited", False)),
                source=str(raw_binding.get("source") or "").strip()[:200],
                values=[
                    str(v).strip() for v in (raw_binding.get("values") or []) if v
                ],
            )
            # Guard: cited=true requires at least one value
            if binding.cited and not binding.values:
                binding.cited = False
        sub_decisions.append(SubDecision(
            id=str(raw_sd.get("id") or "").strip(),
            phrase=str(raw_sd.get("phrase") or "").strip()[:200],
            interpretations=interps,
            likely_intent=str(raw_sd.get("likely_intent") or "").strip(),
            reasoning=str(raw_sd.get("reasoning") or "").strip()[:400],
            policy_fact_binding=binding,
        ))

    # Parse missing_data_dimensions — accept both strings and {dimension,explanation} dicts
    mdd_raw = obj.get("missing_data_dimensions") or []
    missing: list[str] = []
    for m in mdd_raw:
        if isinstance(m, str) and m.strip():
            missing.append(m.strip())
        elif isinstance(m, dict):
            dim = str(m.get("dimension") or "").strip()
            exp = str(m.get("explanation") or "").strip()
            if dim:
                missing.append(f"{dim}: {exp}" if exp else dim)

    return PlanSpec(
        sub_decisions=sub_decisions,
        unambiguous_filters=[
            str(f) for f in (obj.get("unambiguous_filters") or []) if f
        ],
        missing_data_dimensions=missing,
        proceed=bool(obj.get("proceed", True)),
    )


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


# ── VERIFY step (mechanical dry-check) ──────────────────────────────────

def dry_check_interpretations(
    plan: PlanSpec, dfs: dict[str, pd.DataFrame]
) -> ResolvedPlan:
    """Run each likely-intent interpretation against the actual data.

    Enforcement order per sub_decision:

      1. If policy_fact_binding.cited == true:
         Validate that the chosen interpretation's filter_sketch mentions
         ALL bound values. If not, REJECT that interpretation and either
         (a) pick an alternate interpretation that does mention them, or
         (b) synthesize a minimal filter_sketch from the bound values.
         This is the structural override — the planner cannot ignore
         policy facts that it itself declared as citable.

      2. Otherwise (or after policy enforcement):
         Dry-run each candidate filter_sketch against the real data.
         Reject dead-ends (row count 0). Fall through to alternates.

    Mechanical, no LLM. Evaluates filter_sketch in a restricted sandbox.
    """
    chosen: dict[str, str] = {}
    dry_log: list[DryCheckResult] = []
    all_filters: list[str] = list(plan.unambiguous_filters)
    df_names: set[str] = set(dfs.keys())

    for sd in plan.sub_decisions:
        picked_id: str | None = None

        # ── Structural filter 0: reject non-evaluable sketches ─────
        # (AST check — drops pseudo-code like "team_completion_rate < 90")
        evaluable_interps: list[Interpretation] = []
        for interp in sd.interpretations:
            ok, reason = _is_evaluable_sketch(interp.filter_sketch, df_names)
            if ok:
                evaluable_interps.append(interp)
            else:
                dry_log.append(DryCheckResult(
                    sub_decision_id=sd.id,
                    interpretation_id=interp.id,
                    full_row_count=-1,
                    empty_cascade=True,
                    notes=f"rejected by AST check: {reason}",
                ))

        # If NO interpretation is evaluable, keep planner's likely_intent
        # as-is (code-gen may still produce sensible code using it).
        if not evaluable_interps:
            picked_id = sd.likely_intent
            fb = next((i for i in sd.interpretations if i.id == picked_id),
                     sd.interpretations[0] if sd.interpretations else None)
            if fb:
                all_filters.append(fb.filter_sketch)
            chosen[sd.id] = picked_id
            continue

        # Reorder so likely_intent goes first among evaluable
        ordered_eval = sorted(
            evaluable_interps,
            key=lambda i: 0 if i.id == sd.likely_intent else 1,
        )

        # ── Structural filter 1: policy-fact binding enforcement ──
        binding = sd.policy_fact_binding
        if binding.cited and binding.values:
            # NEW: check OUTPUT contains bound values (not just sketch text).
            # Falls back to sketch-text check if the result-based pass fails.
            for interp in ordered_eval:
                contains_all, rc, note = _result_contains_bound_values(
                    interp, dfs, binding.values
                )
                if contains_all:
                    picked_id = interp.id
                    all_filters.append(interp.filter_sketch)
                    dry_log.append(DryCheckResult(
                        sub_decision_id=sd.id,
                        interpretation_id=interp.id,
                        full_row_count=rc,
                        empty_cascade=False,
                        notes=f"policy-fact RESULT anchor matched ({binding.source}): {note[:80]}",
                    ))
                    break
            if picked_id is None:
                # No evaluable interpretation's output contains bound values;
                # fall back to sketch-text literal match as a weaker check.
                for interp in ordered_eval:
                    if _filter_sketch_cites_all_values(interp.filter_sketch, binding.values):
                        picked_id = interp.id
                        all_filters.append(interp.filter_sketch)
                        dry_log.append(DryCheckResult(
                            sub_decision_id=sd.id,
                            interpretation_id=interp.id,
                            full_row_count=-1,
                            empty_cascade=False,
                            notes=f"policy-fact sketch-text match ({binding.source})",
                        ))
                        break
            if picked_id is None:
                # No interpretation honored the binding — synthesize one.
                synth = _synthesize_binding_filter(binding, sd, dfs)
                all_filters.append(synth)
                picked_id = f"{sd.id}.BOUND"
                dry_log.append(DryCheckResult(
                    sub_decision_id=sd.id,
                    interpretation_id=picked_id,
                    full_row_count=-1,
                    empty_cascade=False,
                    notes=f"policy-fact binding SYNTHESIZED: {synth[:80]}",
                ))
            chosen[sd.id] = picked_id
            continue

        # ── Standard dry-check path (no binding) ────────────────────
        # Among evaluable interpretations, pick the first that produces
        # a non-empty result. likely_intent wins ties (ordered_eval).
        for interp in ordered_eval:
            rc, cascade, note = _run_one_dry_check(interp, dfs)
            dry_log.append(DryCheckResult(
                sub_decision_id=sd.id,
                interpretation_id=interp.id,
                full_row_count=rc,
                empty_cascade=cascade,
                notes=note,
            ))
            if rc > 0 and not cascade:
                picked_id = interp.id
                all_filters.append(interp.filter_sketch)
                break
        if picked_id is None:
            # All evaluable interpretations produced empty results.
            picked_id = ordered_eval[0].id
            all_filters.append(ordered_eval[0].filter_sketch)
        chosen[sd.id] = picked_id

    fallback = None
    if not plan.proceed:
        fallback = (
            "Corpus lacks required data dimension(s): "
            + "; ".join(plan.missing_data_dimensions)
        )

    return ResolvedPlan(
        chosen=chosen,
        all_filters=all_filters,
        dry_check_log=dry_log,
        fallback_explanation=fallback,
    )


def _filter_sketch_cites_all_values(sketch: str, values: list[str]) -> bool:
    """True iff every bound value appears as a substring in the sketch.
    Case-insensitive; string-quoted values accepted."""
    if not sketch or not values:
        return False
    sketch_lower = sketch.lower()
    return all(str(v).lower() in sketch_lower for v in values)


def _synthesize_binding_filter(
    binding: PolicyFactBinding, sd: SubDecision, dfs: dict[str, pd.DataFrame]
) -> str:
    """Best-effort synthesis of a filter_sketch from a policy binding that
    the planner failed to encode in any interpretation. We look at the
    sub_decision's interpretations to infer the target column, then emit
    a `.isin([...])` filter. If we can't identify the column, fall back
    to a comment-only sketch (code-gen will pick it up).
    """
    # Try to extract table + column from the first interpretation's sketch
    import re as _re
    first_sketch = sd.interpretations[0].filter_sketch if sd.interpretations else ""
    m = _re.search(r"(df_\w+)\[.*?['\"](\w+)['\"]", first_sketch)
    if m:
        table, col = m.group(1), m.group(2)
        vals = ", ".join(repr(v) for v in binding.values)
        return f"{table}[{table}['{col}'].isin([{vals}])]"
    # Fallback — emit the binding as a comment so code-gen sees it
    vals = ", ".join(repr(v) for v in binding.values)
    return f"# policy_binding: use only values [{vals}] from {binding.source}"


def _order_interpretations(sd: SubDecision) -> list[Interpretation]:
    """Likely-intent first, then the rest in original order."""
    primary = [i for i in sd.interpretations if i.id == sd.likely_intent]
    rest = [i for i in sd.interpretations if i.id != sd.likely_intent]
    return primary + rest


_EVAL_SAFE_BUILTINS = {
    "abs": abs, "len": len, "max": max, "min": min, "sum": sum,
    "set": set, "list": list, "dict": dict, "tuple": tuple,
    "str": str, "int": int, "float": float, "bool": bool,
    "sorted": sorted, "enumerate": enumerate, "range": range,
    "True": True, "False": False, "None": None,
}


# Names allowed to appear in a filter_sketch. Anything else (e.g. an
# intermediate variable the planner invented like "team_completion_rate"
# or "training_by_employee") means the sketch is pseudo-code, not a
# self-contained expression — reject it before dry-check.
_SKETCH_BUILTIN_NAMES = set(_EVAL_SAFE_BUILTINS.keys()) | {
    "pd", "np", "lambda",  # pd / np imports; lambda for anonymous funcs
}


def _is_evaluable_sketch(expr: str, df_names: set[str]) -> tuple[bool, str]:
    """AST-based check: does this sketch reference only df_<name> +
    known safe names? No pseudo-code, no intermediate variables.

    Returns (ok, reason). The parser runs BEFORE dry-check, so we can
    reject violators without paying the cost of a failed eval.
    """
    import ast
    if not expr or not expr.strip():
        return False, "empty sketch"
    # Strip trailing semicolons/newlines
    src = expr.strip().rstrip(";")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        return False, f"syntax error: {e.msg}"
    allowed_df = {f"df_{n}" for n in df_names}
    allowed = allowed_df | _SKETCH_BUILTIN_NAMES
    unknown: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in allowed:
                unknown.add(node.id)
        elif isinstance(node, ast.Lambda):
            # Lambda-arg names are local; ignore them from the global check.
            # But we still walk the body for outer Name refs.
            pass
    # Filter out names that are lambda parameters (they're ok as locals)
    lambda_params: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Lambda):
            for arg in node.args.args:
                lambda_params.add(arg.arg)
    unknown -= lambda_params
    if unknown:
        return False, f"unknown names: {sorted(unknown)}"
    return True, "ok"


def _result_contains_bound_values(
    interp: Interpretation,
    dfs: dict[str, pd.DataFrame],
    bound_values: list[str],
) -> tuple[bool, int, str]:
    """Policy-fact-anchored row hint: does running this sketch produce a
    result whose ROW DATA contains all `bound_values`?

    Works where `_filter_sketch_cites_all_values` can't — when values
    are expected to APPEAR in the output (e.g. "Engineering" in a list
    of flagged depts) rather than be LITERALS in the sketch itself.

    Returns (contains_all, row_count, notes). Never raises.
    """
    sketch = interp.filter_sketch.strip()
    if not sketch or not bound_values:
        return False, 0, "no sketch or no bound values"
    namespace: dict[str, Any] = {
        "__builtins__": _EVAL_SAFE_BUILTINS,
        "pd": pd,
    }
    for name, df in dfs.items():
        namespace[f"df_{name}"] = df
    try:
        result = eval(sketch, namespace)  # noqa: S307 — sandboxed namespace
    except Exception as exc:
        return False, 0, f"eval error: {type(exc).__name__}: {str(exc)[:80]}"
    # Extract searchable text from the result
    if isinstance(result, pd.DataFrame):
        if result.empty:
            return False, 0, "empty dataframe"
        # Flatten first 200 rows across all columns as a text blob
        sample = result.head(200)
        haystack = " ".join(
            sample[c].astype(str).str.cat(sep=" ") for c in sample.columns
        ).lower()
        rc = len(result)
    elif isinstance(result, pd.Series):
        if result.empty:
            return False, 0, "empty series"
        haystack = " ".join(result.head(200).astype(str).tolist()).lower()
        rc = len(result)
    elif isinstance(result, (list, set, tuple)):
        if not result:
            return False, 0, "empty collection"
        haystack = " ".join(str(x) for x in list(result)[:200]).lower()
        rc = len(result)
    else:
        haystack = str(result).lower()
        rc = 1
    # Require ALL bound values to appear somewhere in the output text
    contains_all = all(str(v).lower() in haystack for v in bound_values)
    note = (
        f"row_count={rc}; contains_all={contains_all}; "
        f"found={[v for v in bound_values if str(v).lower() in haystack]}"
    )
    return contains_all, rc, note


def _run_one_dry_check(
    interp: Interpretation, dfs: dict[str, pd.DataFrame]
) -> tuple[int, bool, str]:
    """Return (row_count, empty_cascade_flag, notes). row_count is the
    count of rows the filter keeps. empty_cascade is True if the filter
    evaluates to a non-DataFrame result or produces an obvious error."""
    sketch = interp.filter_sketch.strip()
    if not sketch:
        return 0, True, "empty filter_sketch"
    if any(unsafe in sketch for unsafe in ("__", "import ", "open(", "exec(", "eval(")):
        return 0, True, "unsafe-looking filter sketch; skipped"

    namespace: dict[str, Any] = {
        "__builtins__": _EVAL_SAFE_BUILTINS,
        "pd": pd,
    }
    for name, df in dfs.items():
        namespace[f"df_{name}"] = df

    try:
        result = eval(sketch, namespace)  # noqa: S307 — sandboxed by namespace
    except Exception as exc:
        return 0, True, f"eval error: {type(exc).__name__}: {str(exc)[:80]}"

    if isinstance(result, pd.DataFrame):
        return len(result), len(result) == 0, "dataframe"
    if isinstance(result, pd.Series):
        if result.dtype == bool:
            return int(result.sum()), int(result.sum()) == 0, "boolean mask"
        return len(result), len(result) == 0, "series"
    if isinstance(result, (set, list, tuple)):
        return len(result), len(result) == 0, f"{type(result).__name__}"
    # Scalar — treat as always-present (can't really dry-check a scalar filter)
    return 1, False, f"scalar: {type(result).__name__}"


# ── Formatter for CODE-GEN prompt ───────────────────────────────────────

def format_resolved_plan_for_prompt(
    plan: PlanSpec, resolved: ResolvedPlan
) -> str:
    """Render a resolved plan into a prompt-ready block for CODE-GEN.

    Replaces term_resolver's output — with the ADDITIONAL guarantee that
    every interpretation listed has been dry-checked against the data.
    """
    if resolved.fallback_explanation:
        return (
            "=== PLAN: CANNOT PROCEED ===\n"
            f"{resolved.fallback_explanation}\n\n"
            "Return a polite explanation in `result` that cites the\n"
            "missing dimension. Do NOT fabricate a proxy metric.\n"
        )
    if not plan.sub_decisions and not plan.unambiguous_filters:
        return ""

    lines: list[str] = [
        "=== RESOLVED PLAN (pre-dry-checked against real data) ===",
        "Every filter expression below has been evaluated against the",
        "loaded DataFrames and produces a non-empty result. Use these",
        "verbatim — no reinterpretation.",
        "",
    ]
    for sd in plan.sub_decisions:
        chosen_id = resolved.chosen.get(sd.id, sd.likely_intent)
        chosen_interp = next(
            (i for i in sd.interpretations if i.id == chosen_id),
            sd.interpretations[0] if sd.interpretations else None,
        )
        if chosen_interp is None:
            continue
        dry_count = next(
            (r.full_row_count for r in resolved.dry_check_log
             if r.sub_decision_id == sd.id and r.interpretation_id == chosen_id),
            None,
        )
        lines.append(f"  • {sd.phrase!r}")
        lines.append(f"      chose: {chosen_interp.description}")
        lines.append(f"      filter: {chosen_interp.filter_sketch}")
        if dry_count is not None:
            lines.append(f"      dry-check: {dry_count} matching rows")
        if sd.reasoning:
            lines.append(f"      why: {sd.reasoning}")
        lines.append("")

    if plan.unambiguous_filters:
        lines.append("  Unambiguous filters (apply verbatim):")
        for f in plan.unambiguous_filters:
            lines.append(f"    · {f}")
        lines.append("")

    return "\n".join(lines)
