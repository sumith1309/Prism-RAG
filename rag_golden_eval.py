#!/usr/bin/env python3
"""Golden-query regression harness for Prism analytics.

Runs a curated set of natural-language queries against a live backend and
compares the returned analytics payload to structured ground-truth assertions.

Goal: one command, ~2 minutes, tells you whether the last code change
silently regressed a query that was already correct.

Usage:
    # Full run (requires backend on :8765)
    python3 rag_golden_eval.py

    # Just one query
    python3 rag_golden_eval.py --only Q3

    # Against a different backend / user
    python3 rag_golden_eval.py --base-url http://localhost:8765 --user exec --password exec_pass

    # CI mode — exit 1 on any red; exit 0 on all green
    python3 rag_golden_eval.py --ci

Design notes:
  - Talks to /api/chat the same way the frontend does. No internal Python
    imports of the backend — keeps the test independent of refactors to
    store.py / analytics_agent.py.
  - SSE parsing is manual (httpx stream + split on \\n\\n) so we don't pull
    in an sse-client dependency.
  - Assertions are LAX-by-design on JSON paths: we search the entire
    flattened result tree for scalars matching each `path_hint` rather
    than requiring a fixed schema. LLM-generated `result` dicts vary in
    shape run-to-run; a rigid schema check would flag every cosmetic
    change as a regression.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Install with: pip install httpx", file=sys.stderr)
    sys.exit(2)


# ── ANSI colours ─────────────────────────────────────────────────────────

class _C:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    GREY = "\033[90m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def _ok(msg: str) -> str:
    return f"{_C.GREEN}✓{_C.RESET} {msg}"


def _fail(msg: str) -> str:
    return f"{_C.RED}✗{_C.RESET} {msg}"


def _warn(msg: str) -> str:
    return f"{_C.YELLOW}⚠{_C.RESET} {msg}"


# ── SSE client ───────────────────────────────────────────────────────────

def _login(base_url: str, username: str, password: str) -> str:
    resp = httpx.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


@dataclass
class _StreamedResponse:
    analytics: dict[str, Any] | None = None
    tokens: list[str] = field(default_factory=list)
    done: dict[str, Any] | None = None
    events_seen: list[str] = field(default_factory=list)
    raw_chunks: int = 0

    @property
    def answer_text(self) -> str:
        return "".join(self.tokens)


def _stream_chat(base_url: str, token: str, query: str, timeout: float = 180.0) -> _StreamedResponse:
    """POST /api/chat and consume the SSE stream. Returns the parsed response
    with the `analytics` event payload (if any), any text tokens, and the
    final `done` event.
    """
    out = _StreamedResponse()
    body = {
        "query": query,
        "doc_ids": [],
        "history": [],
        "use_rerank": True,
        "use_faithfulness": False,
        "top_k": 8,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/event-stream",
    }
    event_name: str | None = None
    data_buf: list[str] = []

    def _flush_event() -> None:
        nonlocal event_name, data_buf
        if not data_buf:
            event_name = None
            return
        data_raw = "\n".join(data_buf)
        try:
            data = json.loads(data_raw)
        except json.JSONDecodeError:
            data = data_raw
        out.events_seen.append(event_name or "")
        if event_name == "analytics" and isinstance(data, dict):
            out.analytics = data
        elif event_name == "token" and isinstance(data, dict):
            delta = data.get("delta")
            if isinstance(delta, str):
                out.tokens.append(delta)
        elif event_name == "done" and isinstance(data, dict):
            out.done = data
        event_name = None
        data_buf = []

    with httpx.stream("POST", f"{base_url}/api/chat", json=body, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            out.raw_chunks += 1
            if line == "":
                _flush_event()
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_buf.append(line[5:].lstrip())
    _flush_event()
    return out


# ── Assertion engine ─────────────────────────────────────────────────────

@dataclass
class _QueryReport:
    id: str
    label: str
    bucket: str
    passed: bool = True
    checks: list[tuple[bool, str]] = field(default_factory=list)
    latency_s: float = 0.0
    error: str | None = None
    raw_result: Any = None


def _walk_scalars(obj: Any, path: str = ""):
    """Depth-first flatten — yields (path, value) for every scalar leaf in
    a nested dict/list structure. Used by the hint-based scalar search."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_scalars(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_scalars(v, f"{path}[{i}]")
    else:
        yield path, obj


def _walk_strings(obj: Any):
    """Yield every string value in the tree (for must-contain checks)."""
    for _, v in _walk_scalars(obj):
        if isinstance(v, str):
            yield v


def _hint_matches_path(hint: str, path: str) -> bool:
    """Flexible hint matcher. Tries exact substring first, then token-by-token
    (each non-trivial token of the hint must appear somewhere in the path),
    then a stem-ish match stripping common suffixes (employees↔employee)."""
    h = hint.lower().strip()
    p = path.lower()
    if h in p:
        return True
    # Token-wise — every token of length >= 4 in the hint must appear in the path
    tokens = [t for t in re.split(r"[^a-z0-9]+", h) if len(t) >= 4]
    if tokens and all(t in p for t in tokens):
        return True
    # Stem-ish — employees→employee, customers→customer, etc.
    stemmed = re.sub(r"(?:s|es|ed|ing)\b", "", h)
    if stemmed and stemmed != h and stemmed in p:
        return True
    return False


def _find_scalar_by_hints(obj: Any, hints: list[str]) -> tuple[str, Any] | None:
    """Find the first numeric leaf whose path matches any of the hints.
    Returns (path, value) or None.

    Path matching is flexible: `_hint_matches_path` handles singular/plural
    drift and token-subset matching so 'employees' matches 'employee_count'
    and 'retention_total' matches 'rows[0].retention_bonus_inr_lakhs'.
    """
    candidates: list[tuple[str, Any]] = []
    for path, value in _walk_scalars(obj):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        for h in hints:
            if _hint_matches_path(h, path):
                candidates.append((path, value))
                break
    if not candidates:
        return None
    # Prefer shorter paths (top-level summary fields over nested detail rows)
    candidates.sort(key=lambda pv: len(pv[0]))
    return candidates[0]


def _extract_numbers_from_strings(obj: Any, hints: list[str]) -> list[tuple[str, float]]:
    """When the LLM returns pandas DataFrames as .to_string() blobs (instead
    of proper dicts), numeric values live inside strings. Scan every string
    field whose key/path matches a hint and pull out numbers near the hint
    token.

    Returns list of (path, number) candidates. Caller decides which to use.
    """
    out: list[tuple[str, float]] = []
    number_re = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+\.?\d*")
    for path, value in _walk_scalars(obj):
        if not isinstance(value, str) or len(value) < 10:
            continue
        path_matches_hint = any(_hint_matches_path(h, path) for h in hints)
        for m in number_re.finditer(value):
            raw = m.group(0).replace(",", "")
            try:
                n = float(raw)
            except ValueError:
                continue
            # If the hint tokens appear in a small window around the number,
            # or if the path itself matches a hint, consider this candidate
            if path_matches_hint:
                out.append((f"{path}<string:num@{m.start()}>", n))
                continue
            window = value[max(0, m.start() - 40) : m.end() + 40].lower()
            if any(_hint_matches_path(h, window) for h in hints):
                out.append((f"{path}<string:ctx@{m.start()}>", n))
    return out


def _sum_column_across_rows(obj: Any, hints: list[str]) -> tuple[str, float] | None:
    """Q2-style aggregates: the LLM returns `rows: [{retention_bonus_inr_lakhs: 22.45}, ...]`
    and the ground-truth total is the SUM of a named column across rows.
    If one column's name matches the hints AND appears in multiple rows,
    return the sum along with the column path.
    """
    if not isinstance(obj, dict):
        return None
    rows = obj.get("rows")
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    # Collect candidate columns: numeric, name matches a hint, present in most rows
    col_sums: dict[str, float] = {}
    col_counts: dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k, v in r.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if not any(_hint_matches_path(h, k) for h in hints):
                continue
            col_sums[k] = col_sums.get(k, 0.0) + float(v)
            col_counts[k] = col_counts.get(k, 0) + 1
    if not col_sums:
        return None
    # Prefer the column that appears in the most rows (avoids picking a
    # stray row-level field that only exists in 1 of 13 rows)
    best_col = max(col_sums, key=lambda k: col_counts[k])
    return f"sum(rows[*].{best_col})", col_sums[best_col]


def _within_tolerance(
    actual: float, expected: float, tol_abs: float | None, tol_pct: float | None
) -> bool:
    if tol_abs is not None:
        if abs(actual - expected) <= tol_abs:
            return True
    if tol_pct is not None:
        if expected == 0:
            return abs(actual) <= (tol_pct / 100.0)
        if abs(actual - expected) / abs(expected) * 100.0 <= tol_pct:
            return True
    return tol_abs is None and tol_pct is None  # no tolerance given → strict equality fallback


def _check_rows(actual_result: Any, expected_rows: dict) -> tuple[bool, str]:
    expected = expected_rows.get("value")
    tol_abs = expected_rows.get("tolerance_abs", 0)
    # Pull row count out of the result — could be result.total_rows, or a
    # top-level list length, or missing for scalar results
    total: int | None = None
    if isinstance(actual_result, dict):
        total = actual_result.get("total_rows")
        if total is None:
            rows = actual_result.get("rows")
            if isinstance(rows, list):
                total = len(rows)
    if total is None:
        # Scalar result — no row check applicable, pass by default
        return True, f"n/a (scalar result; expected_rows={expected})"
    ok = abs(total - expected) <= tol_abs
    return ok, f"rows={total} expected={expected} (±{tol_abs})"


def _check_must_contain(
    actual_result: Any, strings: list[str], negate: bool = False
) -> list[tuple[bool, str]]:
    """For each string, check whether it appears in any cell of the result."""
    all_text = " \n ".join(_walk_strings(actual_result)).lower()
    out: list[tuple[bool, str]] = []
    for s in strings:
        hit = s.lower() in all_text
        if negate:
            ok = not hit
            tag = f"absent: {s!r}" if ok else f"UNEXPECTED: {s!r} found"
        else:
            ok = hit
            tag = f"present: {s!r}" if ok else f"MISSING: {s!r}"
        out.append((ok, tag))
    return out


def _check_scalar(actual_result: Any, spec: dict) -> tuple[bool, str]:
    name = spec["name"]
    expected = spec["expected"]
    hints = spec.get("path_hints") or [name]
    tol_abs = spec.get("tolerance_abs")
    tol_pct = spec.get("tolerance_pct")
    allow_zero = spec.get("allow_zero_until_phase3", False)
    allow_missing = spec.get("allow_missing_until_phase3", False)
    search_mode = spec.get("search", "auto")  # "direct" | "sum_rows" | "string_scan" | "auto"

    def _score_candidate(cand: tuple[str, Any]) -> tuple[bool, str]:
        path, actual = cand
        if allow_zero and actual in (0, 0.0):
            return True, f"{_C.GREY}{name}={actual} at {path} (allowed zero until Phase 3){_C.RESET}"
        if _within_tolerance(float(actual), float(expected), tol_abs, tol_pct):
            return True, f"{name}={actual} ≈ {expected} at {path}"
        tol_str = f"±{tol_abs}" if tol_abs is not None else f"±{tol_pct}%"
        return False, f"{name}={actual} vs expected {expected} {tol_str} at {path}"

    # Collect all candidates across strategies, pick the best-matching one.
    candidates: list[tuple[str, Any]] = []

    if search_mode in ("direct", "auto"):
        direct = _find_scalar_by_hints(actual_result, hints)
        if direct is not None:
            candidates.append(direct)

    if search_mode in ("sum_rows", "auto"):
        summed = _sum_column_across_rows(actual_result, hints)
        if summed is not None:
            candidates.append(summed)

    if search_mode in ("string_scan", "auto"):
        string_hits = _extract_numbers_from_strings(actual_result, hints)
        candidates.extend(string_hits)

    if not candidates:
        if allow_missing:
            return True, f"{_C.GREY}{name} missing (allowed until Phase 3){_C.RESET}"
        return False, f"{name} NOT FOUND in result (hints={hints})"

    # Ranking: (1) in-tolerance first, (2) non-string paths, (3) distance
    # to expected value. Last one catches the Q5 case where string-scan
    # returned both "0.0" and "2957.81" — we pick the one nearer the truth.
    def _rank(cand: tuple[str, Any]) -> tuple[int, int, float]:
        path, actual = cand
        in_tol = _within_tolerance(float(actual), float(expected), tol_abs, tol_pct)
        is_string = "<string:" in path
        try:
            dist = abs(float(actual) - float(expected))
        except Exception:
            dist = float("inf")
        return (0 if in_tol else 1, 1 if is_string else 0, dist)

    candidates.sort(key=_rank)
    best = candidates[0]
    return _score_candidate(best)


def _assess_query(spec: dict, stream: _StreamedResponse) -> _QueryReport:
    rpt = _QueryReport(id=spec["id"], label=spec["label"], bucket=spec["bucket"])
    if stream.analytics is None:
        rpt.passed = False
        rpt.error = (
            "No analytics event in stream. "
            f"Saw events: {', '.join(stream.events_seen) or '(none)'}. "
            f"Answer text: {stream.answer_text[:200]!r}"
        )
        return rpt
    if not stream.analytics.get("ok"):
        rpt.passed = False
        rpt.error = f"analytics.ok=False; error={stream.analytics.get('error')!r}"
        return rpt

    result = stream.analytics.get("result")
    rpt.raw_result = result
    expected = spec["expected"]

    # 1. Row count
    if "total_rows" in expected:
        ok, msg = _check_rows(result, expected["total_rows"])
        rpt.checks.append((ok, msg))
        if not ok:
            rpt.passed = False

    # 2. Scalar checks (named facts)
    for sc in expected.get("scalar_checks", []) or []:
        ok, msg = _check_scalar(result, sc)
        rpt.checks.append((ok, msg))
        if not ok:
            rpt.passed = False

    # 3. Must-contain strings
    for ok, msg in _check_must_contain(result, expected.get("must_contain_strings_any_cell", []) or []):
        rpt.checks.append((ok, msg))
        if not ok:
            rpt.passed = False

    # 4. Must-NOT-contain strings
    for ok, msg in _check_must_contain(result, expected.get("must_not_contain_strings", []) or [], negate=True):
        rpt.checks.append((ok, msg))
        if not ok:
            rpt.passed = False

    return rpt


# ── Driver ───────────────────────────────────────────────────────────────

def _run_once(base_url: str, token: str, spec: dict) -> tuple[_QueryReport, _StreamedResponse | None]:
    """Run one query once. Returns (report, stream_or_None). Stream is None
    only when the request itself failed (not when assertions failed)."""
    rpt_id = spec["id"]
    label = spec["label"]
    bucket = spec["bucket"]
    t0 = time.perf_counter()
    try:
        stream = _stream_chat(base_url, token, spec["query"])
    except Exception as e:
        rpt = _QueryReport(id=rpt_id, label=label, bucket=bucket)
        rpt.passed = False
        rpt.error = f"request failed: {type(e).__name__}: {e}"
        rpt.latency_s = time.perf_counter() - t0
        return rpt, None
    rpt = _assess_query(spec, stream)
    rpt.latency_s = time.perf_counter() - t0
    return rpt, stream


def _stability_label(passed: int, total: int, expected_fail: bool = False) -> str:
    """Classify a query's multi-run result. `expected_fail` marks queries
    the current system is known to fail (flag for Phase 3 success)."""
    if total <= 1:
        base = "pass" if passed else "fail"
    elif passed == total:
        base = "stable-pass"
    elif passed == 0:
        base = "stable-fail"
    else:
        base = "flaky"

    if not expected_fail:
        return base
    # Expected-fail variants — these flip the semantics for CI counting
    if base in ("stable-pass", "pass"):
        return "expected-fail-NOW-PASSING"  # Phase 3 win
    if base in ("stable-fail", "fail"):
        return "expected-fail-as-expected"  # baseline state
    return "expected-fail-flaky"  # partial progress


def _stability_tag(label: str) -> str:
    if label in ("pass", "stable-pass"):
        return f"{_C.GREEN}{label}{_C.RESET}"
    if label == "expected-fail-NOW-PASSING":
        return f"{_C.BOLD}{_C.GREEN}{label}{_C.RESET}"  # celebrate
    if label == "expected-fail-as-expected":
        return f"{_C.GREY}{label}{_C.RESET}"  # dim — meets baseline expectation
    if label == "expected-fail-flaky":
        return f"{_C.YELLOW}{label}{_C.RESET}"
    if label == "flaky":
        return f"{_C.YELLOW}{label}{_C.RESET}"
    return f"{_C.RED}{label}{_C.RESET}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8765")
    ap.add_argument("--user", default="exec")
    ap.add_argument("--password", default="exec_pass")
    ap.add_argument("--queries", default="golden_queries.json")
    ap.add_argument("--only", help="Run a single query by id (e.g. Q3)")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Dump full result JSON on failures")
    ap.add_argument("--runs", type=int, default=1,
                    help="Run each query N times to detect flakiness (default 1)")
    ap.add_argument("--require-pass", type=int, default=None,
                    help="In --ci mode, require at least M of N runs pass per query. "
                         "Default = N (all runs must pass, i.e. stable-pass).")
    ap.add_argument("--log-code", metavar="DIR",
                    help="Save the analytics.code from every run to DIR/<query_id>_run<N>.py. "
                         "Useful before Phase 3 to capture LLM filter-shape variance.")
    ap.add_argument("--json-out", metavar="PATH",
                    help="Dump machine-readable results to PATH as JSON. "
                         "Used by diff_baselines.py for pre/post-Phase-3 comparison.")
    ap.add_argument("--label", default="run",
                    help="Label for this run (shown in JSON metadata; distinguishes "
                         "pre-phase3 vs post-phase3 in diffs)")
    ap.add_argument("--ci", action="store_true",
                    help="Exit 1 if any query misses --require-pass threshold; 0 otherwise")
    args = ap.parse_args()

    if args.runs < 1:
        print("ERROR: --runs must be >= 1", file=sys.stderr)
        return 2
    require_pass = args.require_pass if args.require_pass is not None else args.runs
    if require_pass > args.runs:
        print(f"ERROR: --require-pass ({require_pass}) > --runs ({args.runs})", file=sys.stderr)
        return 2

    root = Path(__file__).parent
    spec_path = root / args.queries
    if not spec_path.exists():
        print(f"ERROR: cannot find {spec_path}", file=sys.stderr)
        return 2
    spec_doc = json.loads(spec_path.read_text())
    queries = spec_doc["queries"]
    if args.only:
        queries = [q for q in queries if q["id"] == args.only]
        if not queries:
            print(f"ERROR: no query with id={args.only!r}", file=sys.stderr)
            return 2

    # Prepare code-log directory if requested
    log_code_dir: Path | None = None
    if args.log_code:
        log_code_dir = Path(args.log_code)
        log_code_dir.mkdir(parents=True, exist_ok=True)

    print(f"{_C.BOLD}Prism Golden-Query Regression Harness{_C.RESET}")
    print(f"  backend       {args.base_url}")
    print(f"  user          {args.user}")
    print(f"  queries       {len(queries)} from {spec_path.name}")
    print(f"  runs/query    {args.runs}  (require-pass: {require_pass})")
    if log_code_dir:
        print(f"  code log      {log_code_dir}/")
    print()

    try:
        token = _login(args.base_url, args.user, args.password)
    except Exception as e:
        print(_fail(f"login failed: {e}"))
        return 2

    # Per-query aggregates
    results: dict[str, dict] = {}

    for spec in queries:
        qid = spec["id"]
        print(f"{_C.CYAN}▶ {qid} — {spec['label']}{_C.RESET}")
        print(f"  {_C.GREY}{spec['query'][:110]}{'…' if len(spec['query']) > 110 else ''}{_C.RESET}")
        run_reports: list[_QueryReport] = []
        for run_i in range(1, args.runs + 1):
            rpt, stream = _run_once(args.base_url, token, spec)
            run_reports.append(rpt)

            # Optional: dump generated code to disk for Phase 3 Q3 capture
            if log_code_dir and stream and stream.analytics:
                code = stream.analytics.get("code") or ""
                code_path = log_code_dir / f"{qid}_run{run_i:02d}.py"
                # Header: which run, pass/fail, timing
                header = (
                    f"# {qid} run {run_i}/{args.runs}\n"
                    f"# status: {'PASS' if rpt.passed else 'FAIL'}  "
                    f"latency: {rpt.latency_s:.1f}s\n"
                    f"# query: {spec['query']}\n"
                    f"# " + "-" * 72 + "\n\n"
                )
                code_path.write_text(header + code)

            # Per-run inline output (compact when runs > 1)
            if args.runs == 1:
                if rpt.error:
                    print(f"  {_fail(rpt.error)}")
                for ok, msg in rpt.checks:
                    print(f"  {_ok(msg) if ok else _fail(msg)}")
                status = f"{_C.GREEN}PASS{_C.RESET}" if rpt.passed else f"{_C.RED}FAIL{_C.RESET}"
                print(f"  → {status} in {rpt.latency_s:.1f}s  (bucket: {spec['bucket']})")
            else:
                status_short = f"{_C.GREEN}✓{_C.RESET}" if rpt.passed else f"{_C.RED}✗{_C.RESET}"
                # In multi-run, list only failing checks to keep output readable
                fails = [msg for ok, msg in rpt.checks if not ok]
                fail_note = f"  ({fails[0][:80]})" if fails else ""
                print(f"  run {run_i}/{args.runs}: {status_short}  {rpt.latency_s:.1f}s{fail_note}")

            if args.verbose and not rpt.passed and args.runs == 1:
                print(f"  {_C.GREY}result preview:{_C.RESET}")
                preview = json.dumps(rpt.raw_result, indent=2, default=str)[:2000]
                for line in preview.splitlines():
                    print(f"    {_C.GREY}{line}{_C.RESET}")

        passed_n = sum(1 for r in run_reports if r.passed)
        total_n = len(run_reports)
        expected_fail = spec.get("expected_current") == "fail"
        stability = _stability_label(passed_n, total_n, expected_fail=expected_fail)
        # Per-query require_pass override — queries that are measurably
        # flaky (Q1 at ~76-85% true rate) ship with their own require_pass,
        # typically set at a level corresponding to 2-sigma of their
        # binomial. See findings.md Step 6.
        effective_require_pass = spec.get("require_pass", require_pass)
        # Clamp to [1, total_n] — spec shouldn't demand more passes than
        # runs executed.
        if effective_require_pass > total_n:
            effective_require_pass = total_n
        # CI semantics:
        #   normal query:        CI pass = passed_n >= effective_require_pass
        #   expected-fail query: CI pass = ALWAYS true (failure is the baseline)
        #                        An unexpected PASS is celebrated separately.
        ci_pass = True if expected_fail else (passed_n >= effective_require_pass)
        if args.runs > 1 or expected_fail:
            tag = _stability_tag(stability)
            ratio = f"{passed_n}/{total_n}"
            per_query_note = (
                f" (per-query threshold: ≥{effective_require_pass}/{total_n})"
                if "require_pass" in spec else ""
            )
            ci_marker = "" if ci_pass else f"  {_C.RED}(< require_pass={effective_require_pass}){_C.RESET}"
            print(f"  → {ratio}  [{tag}]{per_query_note}{ci_marker}")
        # Per-run detail for diff analysis: which checks passed/failed,
        # which specific scalar values were extracted. Keeps the JSON
        # output useful without bloating it.
        per_run_detail = []
        for r in run_reports:
            per_run_detail.append({
                "passed": r.passed,
                "latency_s": round(r.latency_s, 2),
                "error": r.error,
                "checks": [{"ok": ok, "msg": msg} for ok, msg in r.checks],
            })
        results[qid] = {
            "label": spec["label"],
            "query": spec["query"],
            "bucket": spec["bucket"],
            "runs": total_n,
            "passed": passed_n,
            "stability": stability,
            "expected_fail": expected_fail,
            "ci_pass": ci_pass,
            "require_pass_effective": effective_require_pass,
            "require_pass_from_spec": spec.get("require_pass"),
            "total_latency_s": round(sum(r.latency_s for r in run_reports), 2),
            "per_run": per_run_detail,
        }
        print()

    # Summary
    total_q = len(results)
    ci_pass_count = sum(1 for r in results.values() if r["ci_pass"])
    stability_counts: dict[str, int] = {}
    for r in results.values():
        stability_counts[r["stability"]] = stability_counts.get(r["stability"], 0) + 1
    # Bucket rollup — easier to scan as 20 queries grows
    bucket_rollup: dict[str, list[str]] = {}
    for qid, r in results.items():
        bucket_rollup.setdefault(r["bucket"], []).append(
            f"{qid}:{r['passed']}/{r['runs']}"
        )

    print(f"{_C.BOLD}Summary{_C.RESET}")
    print(f"  queries        {total_q}")
    print(f"  runs total     {sum(r['runs'] for r in results.values())}")
    print(f"  ci threshold   ≥ {require_pass}/{args.runs} passes per query "
          f"(expected-fail queries auto-pass CI)")
    print(f"  meeting ci     {ci_pass_count}/{total_q}")
    print(f"  stability breakdown:")
    # Prioritize order: wins first, expected-baseline middle, regressions last
    for label in (
        "expected-fail-NOW-PASSING",
        "stable-pass", "pass",
        "expected-fail-flaky",
        "flaky",
        "expected-fail-as-expected",
        "stable-fail", "fail",
    ):
        if label in stability_counts:
            print(f"    {_stability_tag(label):<35}  {stability_counts[label]}")
    # Per-bucket summary
    if len(bucket_rollup) > 1:
        print(f"  by bucket:")
        for bucket in sorted(bucket_rollup):
            print(f"    {bucket:<10} {'  '.join(bucket_rollup[bucket])}")
    # Call out offenders + wins
    for watch, tag in (
        ("expected-fail-NOW-PASSING", "🎉 newly-possible"),
        ("flaky", "flaky"),
        ("stable-fail", "stable-fail"),
    ):
        offenders = [qid for qid, r in results.items() if r["stability"] == watch]
        if offenders:
            print(f"  {tag:<20} : {', '.join(offenders)}")
    total_time = sum(r["total_latency_s"] for r in results.values())
    print(f"  wall time      {total_time:.1f}s")

    # Optional JSON dump for diff tooling
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "label": args.label,
            "base_url": args.base_url,
            "runs_per_query": args.runs,
            "require_pass": require_pass,
            "queries_file": str(spec_path.name),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "summary": {
                "total_queries": total_q,
                "meeting_ci": ci_pass_count,
                "total_wall_time_s": round(total_time, 1),
                "stability_counts": stability_counts,
            },
            "queries": results,
        }
        json_path.write_text(json.dumps(payload, indent=2, default=str))
        print(f"  json dumped    {json_path}")

    if args.ci:
        return 0 if ci_pass_count == total_q else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
