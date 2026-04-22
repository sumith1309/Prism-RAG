#!/usr/bin/env python3
"""Compare two rag_golden_eval.py --json-out runs. Produces a side-by-side
per-query table showing pass-rate deltas, stability transitions, and any
newly-flaky or newly-fixed queries.

Usage:
    python3 diff_baselines.py pre.json post.json

The typical flow:
    # 1. pre-Phase-3
    python3 rag_golden_eval.py --runs 3 --json-out pre.json --label pre-phase3

    # 2. flip flag: export PRISM_PLANNER=1 && restart uvicorn

    # 3. post-Phase-3
    python3 rag_golden_eval.py --runs 3 --json-out post.json --label post-phase3

    # 4. diff
    python3 diff_baselines.py pre.json post.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class _C:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    GREY = "\033[90m"
    RESET = "\033[0m"


_STABILITY_RANK = {
    "expected-fail-NOW-PASSING": 5,
    "stable-pass": 4,
    "pass": 4,
    "flaky": 2,
    "expected-fail-flaky": 2,
    "expected-fail-as-expected": 1,
    "stable-fail": 0,
    "fail": 0,
}


def _transition_arrow(old: str, new: str) -> tuple[str, str]:
    """Return (arrow, color) describing the move from old → new."""
    if old == new:
        return ("=", _C.GREY)
    o = _STABILITY_RANK.get(old, -1)
    n = _STABILITY_RANK.get(new, -1)
    if n > o:
        return ("↑", _C.GREEN)
    if n < o:
        return ("↓", _C.RED)
    return ("~", _C.YELLOW)


def _fmt_ratio(q: dict) -> str:
    return f"{q['passed']}/{q['runs']}"


def _short_stability(s: str) -> str:
    return {
        "stable-pass": "stable-PASS",
        "stable-fail": "stable-FAIL",
        "flaky": "FLAKY",
        "pass": "PASS",
        "fail": "FAIL",
        "expected-fail-NOW-PASSING": "ef→PASS",
        "expected-fail-as-expected": "ef=fail",
        "expected-fail-flaky": "ef-flaky",
    }.get(s, s)


def _fmt_col(s: str, width: int) -> str:
    # Strip ANSI for width calc
    import re
    clean = re.sub(r"\033\[[0-9;]+m", "", s)
    pad = max(0, width - len(clean))
    return s + " " * pad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pre", help="Pre-change JSON (from --json-out)")
    ap.add_argument("post", help="Post-change JSON (from --json-out)")
    ap.add_argument("--sort-by", choices=("id", "delta"), default="id",
                    help="Row order: natural by id, or by biggest improvement/regression")
    ap.add_argument("--show-checks", action="store_true",
                    help="Dump check-level diff for queries whose status changed")
    args = ap.parse_args()

    try:
        pre = json.loads(Path(args.pre).read_text())
        post = json.loads(Path(args.post).read_text())
    except Exception as e:
        print(f"ERROR loading inputs: {e}", file=sys.stderr)
        return 2

    pre_q = pre.get("queries", {})
    post_q = post.get("queries", {})
    all_ids = sorted(set(pre_q) | set(post_q))

    if not all_ids:
        print("No queries in inputs.", file=sys.stderr)
        return 2

    # Summary header
    pre_meet = pre["summary"]["meeting_ci"]
    post_meet = post["summary"]["meeting_ci"]
    pre_total = pre["summary"]["total_queries"]
    post_total = post["summary"]["total_queries"]
    delta_meet = post_meet - pre_meet

    print(f"{_C.BOLD}Baseline Diff — {pre['label']} → {post['label']}{_C.RESET}")
    print(f"  pre:  {pre_meet}/{pre_total} meeting CI ({pre['runs_per_query']} runs each, "
          f"{pre['summary']['total_wall_time_s']:.0f}s wall)")
    print(f"  post: {post_meet}/{post_total} meeting CI ({post['runs_per_query']} runs each, "
          f"{post['summary']['total_wall_time_s']:.0f}s wall)")
    delta_color = _C.GREEN if delta_meet > 0 else _C.RED if delta_meet < 0 else _C.GREY
    print(f"  delta: {delta_color}{delta_meet:+d}{_C.RESET} queries meeting CI")
    print()

    # Per-query diff
    rows = []
    for qid in all_ids:
        pre_r = pre_q.get(qid)
        post_r = post_q.get(qid)
        if pre_r is None or post_r is None:
            # Query added or removed between runs
            rows.append((qid, "(missing one side)", None, None, None, None, None))
            continue
        old_stab = pre_r["stability"]
        new_stab = post_r["stability"]
        arrow, color = _transition_arrow(old_stab, new_stab)
        delta_passes = post_r["passed"] - pre_r["passed"]
        rows.append((
            qid,
            post_r.get("label", ""),
            _fmt_ratio(pre_r),
            _short_stability(old_stab),
            _fmt_ratio(post_r),
            _short_stability(new_stab),
            (arrow, color, delta_passes, post_r.get("bucket")),
        ))

    if args.sort_by == "delta":
        def _sort_key(row):
            if row[-1] is None:
                return (0, row[0])
            _arrow, _color, delta_p, _bucket = row[-1]
            return (-abs(delta_p), row[0])
        rows.sort(key=_sort_key)

    # Render table
    hdr = f"  {'QID':<4}  {'LABEL':<44}  {'PRE':<6} {'STATE':<12}  →  {'POST':<6} {'STATE':<12}  Δ"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))

    improvements: list[str] = []
    regressions: list[str] = []

    for row in rows:
        qid, label = row[0], row[1]
        if row[2] is None:
            print(f"  {qid:<4}  {label}")
            continue
        pre_ratio, pre_stab, post_ratio, post_stab, meta = row[2], row[3], row[4], row[5], row[6]
        arrow, color, delta_p, bucket = meta
        label_s = label if len(label) <= 43 else label[:40] + "…"
        bucket_tag = {
            "anchor": f"{_C.CYAN}A{_C.RESET}",
            "sir":    f"{_C.CYAN}S{_C.RESET}",
            "edge":   f"{_C.CYAN}E{_C.RESET}",
        }.get(bucket, " ")
        delta_str = f"{color}{arrow}{_C.RESET}"
        if delta_p != 0:
            delta_str += f" ({delta_p:+d})"
        print(
            f"  {qid:<4}{bucket_tag} {label_s:<43}  {pre_ratio:<6} {pre_stab:<12}  →  "
            f"{post_ratio:<6} {post_stab:<12}  {delta_str}"
        )

        # Track big moves for callouts
        if arrow == "↑":
            improvements.append(f"{qid} ({pre_stab} → {post_stab})")
        elif arrow == "↓":
            regressions.append(f"{qid} ({pre_stab} → {post_stab})")

    print()
    if improvements:
        print(f"{_C.BOLD}Improvements{_C.RESET} ({len(improvements)})")
        for i in improvements:
            print(f"  {_C.GREEN}↑{_C.RESET} {i}")
    if regressions:
        print(f"{_C.BOLD}{_C.RED}REGRESSIONS{_C.RESET} ({len(regressions)}) — investigate")
        for r in regressions:
            print(f"  {_C.RED}↓{_C.RESET} {r}")
    if not improvements and not regressions:
        print(f"  {_C.GREY}no stability changes between pre and post{_C.RESET}")

    # Optional check-level drill-down
    if args.show_checks:
        changed = [r[0] for r in rows if r[2] is not None and r[3] != r[5]]
        for qid in changed:
            print()
            print(f"{_C.BOLD}{qid} check-level diff{_C.RESET}")
            pre_checks = _collect_checks(pre_q[qid])
            post_checks = _collect_checks(post_q[qid])
            for k in sorted(set(pre_checks) | set(post_checks)):
                old_rate = pre_checks.get(k, (0, 0))
                new_rate = post_checks.get(k, (0, 0))
                if old_rate == new_rate:
                    continue
                print(f"  {k}")
                print(f"    pre  {old_rate[0]}/{old_rate[1]}   post {new_rate[0]}/{new_rate[1]}")

    return 0


def _collect_checks(q: dict) -> dict[str, tuple[int, int]]:
    """For a single query's per-run data, return {check_msg: (passes, total)}
    — so we can see which specific assertions improved vs regressed."""
    counts: dict[str, tuple[int, int]] = {}
    for run in q.get("per_run", []):
        for c in run.get("checks", []):
            # Normalize the message: strip numeric tails so "rows=22 expected=22"
            # and "rows=0 expected=22" group as the same check.
            msg = c["msg"]
            # Keep first 60 chars — enough to identify the check type
            key = msg[:60]
            p, t = counts.get(key, (0, 0))
            counts[key] = (p + (1 if c["ok"] else 0), t + 1)
    return counts


if __name__ == "__main__":
    sys.exit(main())
