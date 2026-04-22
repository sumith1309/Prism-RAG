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


def score_standard(qry: dict, resp: StreamedResponse) -> QueryReport:
    """Tiers 1-4: must_contain + must_not_contain + optional scalar checks."""
    ans_text = _derive_answer_text(resp)
    rep = QueryReport(id=qry["id"], difficulty=qry["difficulty"],
                      tier_name=qry["tier_name"], label=qry["label"],
                      query=qry["query"], answer_preview=ans_text[:400],
                      events_seen=resp.events_seen,
                      done_event=resp.done,
                      analytics_event=resp.analytics)
    expected = qry.get("expected", {})
    blob = _answer_blob(resp)

    # must_contain_strings_all — every string must appear
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
        rep.checks.append((ok, f"must_contain_any ({len(hits)}/{len(any_list)}): "
                               f"{hits[:3]}"))
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

    # Very loose scalar check — just verifies the expected number appears
    # somewhere in the answer. Full path-based scalar matching (like
    # rag_golden_eval) is overkill for text-only code-docs queries.
    for sc in expected.get("scalar_checks", []):
        expected_val = sc["expected"]
        as_str = str(expected_val).rstrip("0").rstrip(".") if isinstance(expected_val, float) else str(expected_val)
        hit = as_str in blob
        rep.checks.append((hit, f"scalar '{sc['name']}' = {expected_val} "
                                f"{'✓ found' if hit else '✗ missing'}"))
        if not hit:
            rep.passed = False

    return rep


def score_abstention(qry: dict, resp: StreamedResponse) -> QueryReport:
    """Tier 5: must use abstention language, must NOT emit hallucination flags.
    Scores against answer text ONLY (excludes metadata like timestamps)."""
    ans_text = _derive_answer_text(resp)
    rep = QueryReport(id=qry["id"], difficulty=qry["difficulty"],
                      tier_name=qry["tier_name"], label=qry["label"],
                      query=qry["query"], answer_preview=ans_text[:400],
                      events_seen=resp.events_seen,
                      done_event=resp.done,
                      analytics_event=resp.analytics)
    expected = qry.get("expected", {})
    text = _answer_text_only(resp)  # metadata-free scoring surface

    abstention_any = expected.get("abstention_phrases_any", [])
    hallu_flags = expected.get("hallucination_red_flags", [])

    abstained = any(p.lower() in text for p in abstention_any)
    rep.checks.append((abstained,
        f"abstained ({'✓ honest refusal' if abstained else '✗ NO refusal phrase'})"))

    flagged = [f for f in hallu_flags if f.lower() in text]
    clean = len(flagged) == 0
    rep.checks.append((clean,
        f"hallucination check ({'✓ clean' if clean else f'✗ FLAGGED: {flagged}'})"))

    rep.passed = abstained and clean
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
    print(f"\n{_C.B}═══ {domain_name} ═══{_C.Z}  ({domain_dir})")

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
            rep = score_abstention(qry, resp) if is_abstention else score_standard(qry, resp)
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
