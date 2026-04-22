#!/usr/bin/env python3
"""OOD (out-of-distribution) RAG harness runner.

For each domain in ood_harness/domains/<name>/:
  1. Upload the domain's docs once, capture returned doc_ids
  2. For each query in queries.json, stream /api/chat with doc_ids=[...] scoped
  3. Score tier-1..4 by must_contain checks + scalar match
  4. Score tier-5 (abstention) by abstention phrases + hallucination red flags
  5. Write per-domain + overall summary to baseline JSON

Usage:
    python3 ood_harness/ood_eval.py                  # run all populated domains
    python3 ood_harness/ood_eval.py --domain code_docs
    python3 ood_harness/ood_eval.py --json-out ood_harness/baselines/preA.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    print("ERROR: httpx required. pip install httpx", file=sys.stderr)
    sys.exit(2)


HARNESS_ROOT = Path(__file__).parent
DOMAINS_ROOT = HARNESS_ROOT / "domains"
BASELINES_ROOT = HARNESS_ROOT / "baselines"


# ── ANSI ────────────────────────────────────────────────────────────────

class _C:
    G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"
    C = "\033[36m"; B = "\033[1m"; Z = "\033[0m"


def _ok(s: str) -> str:  return f"{_C.G}✓{_C.Z} {s}"
def _no(s: str) -> str:  return f"{_C.R}✗{_C.Z} {s}"
def _warn(s: str) -> str: return f"{_C.Y}⚠{_C.Z} {s}"


# ── API ─────────────────────────────────────────────────────────────────

def login(base_url: str, username: str, password: str) -> str:
    r = httpx.post(f"{base_url}/api/auth/login",
                   json={"username": username, "password": password}, timeout=15.0)
    r.raise_for_status()
    return r.json()["access_token"]


def _list_existing_docs(base_url: str, token: str) -> dict[str, str]:
    """Returns {filename: doc_id} for docs already visible to the user."""
    r = httpx.get(f"{base_url}/api/documents",
                  headers={"Authorization": f"Bearer {token}"}, timeout=30.0)
    r.raise_for_status()
    out = {}
    for d in r.json():
        # Response shape: {doc_id, filename, ...}
        fn = d.get("filename") or d.get("name")
        did = d.get("doc_id") or d.get("id")
        if fn and did:
            out[fn] = did
    return out


def upload_docs(base_url: str, token: str, doc_paths: list[Path]) -> list[str]:
    """Idempotent upload. If a filename already exists server-side, reuse its
    doc_id instead of re-uploading. Fact extraction + embedding can take 60-180s
    per new doc, so client timeout is 600s."""
    existing = _list_existing_docs(base_url, token)
    to_upload: list[Path] = []
    out: list[str] = []
    for p in doc_paths:
        if p.name in existing:
            out.append(existing[p.name])
            print(f"    reuse {p.name} → {existing[p.name]}")
        else:
            to_upload.append(p)
            out.append("")  # placeholder; filled in after upload

    if to_upload:
        files = [("files", (p.name, p.read_bytes(), "text/markdown"))
                 for p in to_upload]
        headers = {"Authorization": f"Bearer {token}"}
        data = {"classification": "1"}  # PUBLIC — retrieval scoped per query anyway
        r = httpx.post(f"{base_url}/api/documents",
                       files=files, data=data, headers=headers, timeout=600.0)
        r.raise_for_status()
        resp = r.json()
        up_iter = iter(resp)
        # Fill placeholders in original order
        for i, p in enumerate(doc_paths):
            if out[i] == "":
                item = next(up_iter)
                if item.get("status") != "ok":
                    raise RuntimeError(
                        f"Upload failed for {item.get('filename')}: {item.get('error')}")
                out[i] = item["doc_id"]
    return out


@dataclass
class StreamedResponse:
    analytics: dict[str, Any] | None = None
    tokens: list[str] = field(default_factory=list)
    done: dict[str, Any] | None = None
    events_seen: list[str] = field(default_factory=list)

    @property
    def answer(self) -> str:
        return "".join(self.tokens)


def stream_chat(base_url: str, token: str, query: str, doc_ids: list[str],
                timeout: float = 180.0) -> StreamedResponse:
    out = StreamedResponse()
    body = {
        "query": query,
        "doc_ids": doc_ids,
        "history": [],
        "use_rerank": True,
        "use_faithfulness": False,
        "top_k": 8,
    }
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    event_name: str | None = None
    data_buf: list[str] = []

    def _flush():
        nonlocal event_name, data_buf
        if not data_buf:
            event_name = None
            return
        raw = "\n".join(data_buf)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
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

    with httpx.stream("POST", f"{base_url}/api/chat", json=body, headers=headers,
                      timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line == "":
                _flush()
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_buf.append(line[5:].lstrip())
    _flush()
    return out


# ── Scoring ─────────────────────────────────────────────────────────────

@dataclass
class QueryReport:
    id: str
    difficulty: int
    tier_name: str
    label: str
    query: str
    passed: bool = True
    checks: list[tuple[bool, str]] = field(default_factory=list)
    latency_s: float = 0.0
    answer_preview: str = ""
    events_seen: list[str] = field(default_factory=list)
    done_event: Any = None
    analytics_event: Any = None
    answer_mode: str = ""
    tables_joined_preview: list = field(default_factory=list)
    route_ok: bool = True
    error: str | None = None


def _answer_blob(resp: StreamedResponse) -> str:
    """Combined text surface for string-contains checks. Covers both freeform
    tokens and structured analytics payloads (flattened to JSON)."""
    parts = [resp.answer]
    if resp.analytics:
        parts.append(json.dumps(resp.analytics, ensure_ascii=False))
    if resp.done:
        parts.append(json.dumps(resp.done, ensure_ascii=False))
    return "\n".join(parts).lower()


def _values_match(a, b, tol_abs=0, tol_pct=None) -> bool:
    """Numeric match with optional absolute + percent tolerances."""
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if tol_abs is None:
        tol_abs = 0
    if abs(a - b) <= tol_abs:
        return True
    if tol_pct is not None and b != 0 and abs((a - b) / b) * 100 <= tol_pct:
        return True
    return False


def _find_value_in_result(analytics_event, expected_value, path_hints,
                          tol_abs=0, tol_pct=None) -> tuple[bool, str]:
    """Fix 1 — match expected value against `analytics.result` specifically,
    NOT the full serialized blob. Prevents the T3 false positive where
    `"3"` appeared in metadata while the actual answer was 8.

    Handles scalar result, string-representing-number, dict (hint-guided),
    and list-of-rows. Returns (matched, diagnostic)."""
    if analytics_event is None:
        return False, "no analytics event"
    result = analytics_event.get("result")
    if result is None:
        return False, "analytics.result is None"

    # Scalar number
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        ok = _values_match(result, expected_value, tol_abs, tol_pct)
        return ok, f"scalar result={result} vs expected={expected_value}"

    # String — try parse as number, else substring
    if isinstance(result, str):
        try:
            v = float(result.strip())
            ok = _values_match(v, expected_value, tol_abs, tol_pct)
            return ok, f"string-as-number result={v} vs expected={expected_value}"
        except ValueError:
            ok = str(expected_value) in result
            return ok, f"string result contains '{expected_value}'? {ok}"

    # Dict — hint-guided lookup
    if isinstance(result, dict):
        hint_matches = []
        for k, v in result.items():
            if any(h.lower() in k.lower() for h in path_hints):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if _values_match(v, expected_value, tol_abs, tol_pct):
                        return True, f"dict['{k}']={v} (hint-match)"
                    hint_matches.append((k, v))
                elif isinstance(v, str) and str(expected_value) in v:
                    return True, f"dict['{k}']='{v[:40]}' (hint-match)"
        if hint_matches:
            return False, f"hint key found but value mismatch: {hint_matches[:3]}"
        if not path_hints:
            # No hints given — loose scan is acceptable
            for k, v in result.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if _values_match(v, expected_value, tol_abs, tol_pct):
                        return True, f"dict['{k}']={v} (no-hint scan)"
        return False, f"no hint-match in keys: {list(result.keys())[:6]}"

    # List of rows
    if isinstance(result, list):
        for i, row in enumerate(result):
            if isinstance(row, dict):
                for k, v in row.items():
                    if any(h.lower() in k.lower() for h in path_hints) and \
                       isinstance(v, (int, float)) and not isinstance(v, bool):
                        if _values_match(v, expected_value, tol_abs, tol_pct):
                            return True, f"rows[{i}]['{k}']={v}"
        return False, "list/rows result, no hint-match"

    return False, f"unhandled result type: {type(result).__name__}"


def _is_structural_abstention(analytics_event) -> tuple[bool, str]:
    """Fix 2 — detect 'I don't know' in structural form (answer: None, etc.)
    Complements phrase-based abstention checks."""
    if analytics_event is None:
        return False, "no analytics"
    result = analytics_event.get("result")
    if result is None:
        return True, "analytics.result is None"
    if isinstance(result, dict):
        ans = result.get("answer")
        if ans is None and "answer" in result:
            return True, "analytics.result.answer is explicitly None"
        if isinstance(ans, str) and not ans.strip():
            return True, "analytics.result.answer is empty string"
    return False, "no structural abstention signal"


def _route_check(done_event, analytics_event, forbidden_routes) -> tuple[bool, str, str, list]:
    """Fix 3 — route assertion. If the response's `answer_mode` is in the
    domain's `forbidden_routes`, the query FAILS regardless of answer match.
    This is the core of Finding 1a: right answer via wrong route is NOT
    architectural correctness. Returns (pass, diagnostic, mode, tables_preview)."""
    mode = (done_event or {}).get("answer_mode", "") if isinstance(done_event, dict) else ""
    tables = []
    if isinstance(analytics_event, dict):
        t = analytics_event.get("tables_joined")
        if isinstance(t, list):
            tables = t[:5]
    if not forbidden_routes:
        return True, f"no route restriction (mode='{mode}')", mode, tables
    if mode in forbidden_routes:
        return False, f"FORBIDDEN route: answer_mode='{mode}' ∈ {forbidden_routes}; tables_joined={tables}", mode, tables
    return True, f"route ok: answer_mode='{mode}'", mode, tables


def _derive_answer_text(resp: StreamedResponse) -> str:
    """Pull the actual answer text. /api/chat often ships the full answer in
    the `done` event rather than (or in addition to) streamed tokens. Try
    tokens first, fall back to done.answer / done.text / done.message."""
    if resp.answer.strip():
        return resp.answer
    if isinstance(resp.done, dict):
        for k in ("answer", "text", "message", "response", "content"):
            v = resp.done.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return ""


def _answer_text_only(resp: StreamedResponse) -> str:
    """Scoring surface that EXCLUDES metadata (timestamps, session IDs, etc.).
    Critical for abstention scoring — we don't want to flag `ts: 2026-04-22`
    as a hallucination about FastAPI 2.0."""
    text = _derive_answer_text(resp)
    # Also include analytics.answer / analytics.explanation-like fields if
    # present — these are LLM-generated content, not metadata.
    if isinstance(resp.analytics, dict):
        for k in ("answer", "explanation", "summary", "reasoning"):
            v = resp.analytics.get(k)
            if isinstance(v, str) and v.strip():
                text = text + "\n" + v
    return text.lower()


def _apply_route_check(rep: QueryReport, resp: StreamedResponse,
                       forbidden_routes: list) -> None:
    """Append the route-assertion check to `rep`. Failing route-check makes
    the query FAIL regardless of answer match. Finding 1a: architectural
    correctness ≠ answer match."""
    ok, msg, mode, tables = _route_check(resp.done, resp.analytics, forbidden_routes or [])
    rep.answer_mode = mode
    rep.tables_joined_preview = tables
    rep.route_ok = ok
    rep.checks.append((ok, f"route assertion: {msg}"))
    if not ok:
        rep.passed = False


def score_standard(qry: dict, resp: StreamedResponse,
                   forbidden_routes: list | None = None) -> QueryReport:
    """Tiers 1-4: answer-match checks (strings + scalar-in-result) + route assertion."""
    ans_text = _derive_answer_text(resp)
    rep = QueryReport(id=qry["id"], difficulty=qry["difficulty"],
                      tier_name=qry["tier_name"], label=qry["label"],
                      query=qry["query"], answer_preview=ans_text[:400],
                      events_seen=resp.events_seen,
                      done_event=resp.done,
                      analytics_event=resp.analytics)
    expected = qry.get("expected", {})
    blob = _answer_blob(resp)

    # must_contain_strings_all — every string must appear in blob
    for s in expected.get("must_contain_strings_all", []):
        hit = s.lower() in blob
        rep.checks.append((hit, f"must_contain_all: '{s}' {'✓' if hit else '✗'}"))
        if not hit:
            rep.passed = False

    # must_contain_strings_any_cell — at least one string must appear
    any_list = expected.get("must_contain_strings_any_cell", [])
    if any_list:
        hits = [s for s in any_list if s.lower() in blob]
        ok = len(hits) >= 1
        rep.checks.append((ok, f"must_contain_any ({len(hits)}/{len(any_list)}): {hits[:3]}"))
        if not ok:
            rep.passed = False

    # must_contain_strings_any_of_lists — at least one from each inner list
    for lst in expected.get("must_contain_strings_any_of_lists", []):
        hits = [s for s in lst if s.lower() in blob]
        ok = len(hits) >= 1
        rep.checks.append((ok, f"any_of_list ({len(hits)}/{len(lst)}): {hits[:3]}"))
        if not ok:
            rep.passed = False

    # must_not_contain_strings
    for s in expected.get("must_not_contain_strings", []):
        hit = s.lower() in blob
        rep.checks.append((not hit, f"must_not_contain: '{s}' "
                                   f"{'✓ absent' if not hit else '✗ PRESENT'}"))
        if hit:
            rep.passed = False

    # Fix 1: scalar_checks match against analytics.result specifically,
    # not the full serialized blob. Prevents T3-style false positives.
    for sc in expected.get("scalar_checks", []):
        expected_val = sc["expected"]
        hints = sc.get("path_hints", [])
        tol_abs = sc.get("tolerance_abs", 0)
        tol_pct = sc.get("tolerance_pct")
        ok, msg = _find_value_in_result(resp.analytics, expected_val, hints,
                                         tol_abs=tol_abs, tol_pct=tol_pct)
        rep.checks.append((ok, f"scalar '{sc['name']}' = {expected_val} → {msg}"))
        if not ok:
            rep.passed = False

    # Fix 3: route assertion
    _apply_route_check(rep, resp, forbidden_routes)
    return rep


def score_abstention(qry: dict, resp: StreamedResponse,
                     forbidden_routes: list | None = None) -> QueryReport:
    """Tier 5: must use abstention language (phrase OR structural),
    must NOT emit hallucination flags. Plus route assertion."""
    ans_text = _derive_answer_text(resp)
    rep = QueryReport(id=qry["id"], difficulty=qry["difficulty"],
                      tier_name=qry["tier_name"], label=qry["label"],
                      query=qry["query"], answer_preview=ans_text[:400],
                      events_seen=resp.events_seen,
                      done_event=resp.done,
                      analytics_event=resp.analytics)
    expected = qry.get("expected", {})
    text = _answer_text_only(resp)  # metadata-free surface

    abstention_any = expected.get("abstention_phrases_any", [])
    hallu_flags = expected.get("hallucination_red_flags", [])

    # Phrase-based abstention
    phrase_abstained = any(p.lower() in text for p in abstention_any)
    # Fix 2: structural abstention (answer: None / empty)
    struct_abstained, struct_msg = _is_structural_abstention(resp.analytics)
    abstained = phrase_abstained or struct_abstained

    form = ("phrase" if phrase_abstained else "") + \
           (("+" if phrase_abstained and struct_abstained else "") if True else "") + \
           ("structural" if struct_abstained else "")
    form = form or "neither"
    rep.checks.append((abstained,
        f"abstained via {form} "
        f"({'✓ honest refusal' if abstained else '✗ NO refusal signal (struct: ' + struct_msg + ')'})"))

    flagged = [f for f in hallu_flags if f.lower() in text]
    clean = len(flagged) == 0
    rep.checks.append((clean,
        f"hallucination check ({'✓ clean' if clean else f'✗ FLAGGED: {flagged}'})"))

    rep.passed = abstained and clean

    # Fix 3: route assertion
    _apply_route_check(rep, resp, forbidden_routes)
    return rep


# ── Runner ──────────────────────────────────────────────────────────────

def discover_domains() -> list[Path]:
    """A domain is populated iff it has queries.json with len(queries) > 0."""
    out = []
    for d in sorted(DOMAINS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        q_path = d / "queries.json"
        if not q_path.exists():
            continue
        try:
            data = json.loads(q_path.read_text())
            if data.get("queries"):
                out.append(d)
        except Exception:
            continue
    return out


def run_domain(base_url: str, token: str, domain_dir: Path) -> dict[str, Any]:
    spec = json.loads((domain_dir / "queries.json").read_text())
    domain_name = spec["domain"]
    forbidden_routes = spec.get("forbidden_routes", [])
    print(f"\n{_C.B}═══ {domain_name} ═══{_C.Z}  ({domain_dir})")
    if forbidden_routes:
        print(f"  forbidden_routes = {forbidden_routes}")

    # Upload docs
    doc_paths = [domain_dir / rel for rel in spec["docs"]]
    for p in doc_paths:
        if not p.exists():
            print(_no(f"missing doc: {p}"))
            return {"domain": domain_name, "error": f"missing {p}"}
    print(f"  uploading {len(doc_paths)} doc(s)…", end=" ", flush=True)
    t0 = time.time()
    doc_ids = upload_docs(base_url, token, doc_paths)
    print(f"{_C.G}ok{_C.Z} in {time.time()-t0:.1f}s → doc_ids={doc_ids}")

    # Run queries
    reports: list[QueryReport] = []
    for qry in spec["queries"]:
        print(f"  [{qry['id']} T{qry['difficulty']} {qry['tier_name']}]…",
              end=" ", flush=True)
        t0 = time.time()
        try:
            resp = stream_chat(base_url, token, qry["query"], doc_ids)
            is_abstention = qry["difficulty"] == 5
            if is_abstention:
                rep = score_abstention(qry, resp, forbidden_routes=forbidden_routes)
            else:
                rep = score_standard(qry, resp, forbidden_routes=forbidden_routes)
            rep.latency_s = round(time.time() - t0, 1)
        except Exception as e:
            rep = QueryReport(id=qry["id"], difficulty=qry["difficulty"],
                              tier_name=qry["tier_name"], label=qry["label"],
                              query=qry["query"], passed=False, error=str(e),
                              latency_s=round(time.time()-t0, 1))
        reports.append(rep)
        tag = _ok("PASS") if rep.passed else _no("FAIL")
        print(f"{tag} ({rep.latency_s}s)")
        for ok, msg in rep.checks:
            mark = _C.G + "  ✓" if ok else _C.R + "  ✗"
            print(f"    {mark}{_C.Z} {msg}")
        if rep.error:
            print(f"    {_C.R}error: {rep.error}{_C.Z}")

    # Summary
    passed = sum(1 for r in reports if r.passed)
    total = len(reports)
    print(f"  {_C.B}{domain_name}: {passed}/{total}{_C.Z}")
    return {
        "domain": domain_name,
        "doc_ids": doc_ids,
        "passed": passed,
        "total": total,
        "queries": [asdict(r) for r in reports],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8765")
    ap.add_argument("--user", default="exec")
    ap.add_argument("--password", default="exec_pass")
    ap.add_argument("--domain", help="Run only this domain (e.g. code_docs)")
    ap.add_argument("--json-out", help="Path for machine-readable baseline JSON")
    ap.add_argument("--label", default="ood_baseline", help="label in JSON")
    args = ap.parse_args()

    BASELINES_ROOT.mkdir(exist_ok=True)

    print(f"{_C.B}OOD RAG harness{_C.Z}  backend={args.base_url}  user={args.user}")
    token = login(args.base_url, args.user, args.password)
    print(_ok("auth ok"))

    domains = discover_domains()
    if args.domain:
        domains = [d for d in domains if d.name == args.domain]
    if not domains:
        print(_warn("no populated domains found"))
        return 1
    print(f"  domains: {[d.name for d in domains]}")

    t0 = time.time()
    domain_results = [run_domain(args.base_url, token, d) for d in domains]
    wall = round(time.time() - t0, 1)

    total_passed = sum(r.get("passed", 0) for r in domain_results)
    total_queries = sum(r.get("total", 0) for r in domain_results)
    print(f"\n{_C.B}OVERALL: {total_passed}/{total_queries}{_C.Z}  wall={wall}s")

    out = {
        "label": args.label,
        "wall_seconds": wall,
        "passed": total_passed,
        "total": total_queries,
        "domains": domain_results,
    }
    out_path = Path(args.json_out) if args.json_out else \
        BASELINES_ROOT / f"{args.label}_{int(time.time())}.json"
    out_path.parent.mkdir(exist_ok=True, parents=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"  → {out_path}")
    return 0 if total_passed == total_queries else 1


if __name__ == "__main__":
    sys.exit(main())
