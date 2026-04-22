#!/usr/bin/env python3
"""Classify Q3 --log-code runs by filter interpretation.

Q3 asks "haven't bothered with any certifications". Two interpretations:
  - Interpretation A (correct): anti-join on people WHO HAVE completed
    external certs. Expressed as `~isin(certified_emp_ids)`.
  - Interpretation B (wrong): direct-join on people with PENDING external
    cert rows. Expressed as `isin(non_completed_cert_ids)` or equivalent.

Ship threshold (per planner_DESIGN.md):
  - 10/10 row-count correct AND ≥ 9/10 using interpretation A → SHIP
  - 10/10 correct AND 10/10 A → pristine
  - 10/10 correct AND ≤ 8/10 A → investigate
  - < 10/10 correct → Phase 3 failed on primary case

Usage:
    python3 analyze_q3_interpretations.py /tmp/q3_post_phase3
    python3 analyze_q3_interpretations.py q3_pre_phase3_capture   # pre baseline
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


class _C:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BOLD = "\033[1m"
    GREY = "\033[90m"
    RESET = "\033[0m"


# Interpretation-A signature: anti-join with ~...isin(certified-set) where
# the set was built from Completed external-cert rows. Allow any prefix
# between `~` and `.isin(` (covers `~df['col'].isin(...)`).
_INTERP_A_SIG = re.compile(
    r"~[^\n]{1,80}\.isin\([^)]*"
    r"(?:certified|completed_cert|completed_external|cert_completed)",
    re.IGNORECASE,
)

# Interpretation-B signature: direct-join with isin() on the NON-completed
# (pending / overdue / gap / uncertified) set.
_INTERP_B_SIG = re.compile(
    r"[^~]\.isin\([^)]*"
    r"(?:uncertified|non_completed|cert_gap|pending_cert|overdue_cert|incomplete_cert)",
    re.IGNORECASE,
)


def _extract_status(content: str) -> str:
    m = re.search(r"# status:\s*(PASS|FAIL)", content)
    return m.group(1) if m else "?"


def _classify(content: str) -> str:
    # Strip comment header so the header's "ESOPs" mentions don't skew signatures
    body_start = content.find("\n\n")
    body = content[body_start:] if body_start > 0 else content

    # Prefer A over B: some code first computes completed_set then uses
    # ~isin; that's interpretation A even if the file also mentions
    # "non_completed" in intermediate variables. The decisive signal is
    # the FINAL filter.
    a_hits = len(_INTERP_A_SIG.findall(body))
    b_hits = len(_INTERP_B_SIG.findall(body))

    # Secondary heuristic — look at the FINAL `result =` line
    final_result = ""
    for line in reversed(body.splitlines()):
        if line.strip().startswith("result ="):
            # Grab a 4-line window around the final result to see its filter
            idx = body.rfind("result =")
            final_result = body[max(0, idx - 200): idx + 400]
            break

    final_is_anti = bool(re.search(r"~[\w\.]*\.isin\(", final_result))
    final_is_direct = bool(re.search(r"[^~]\.isin\(", final_result))

    # Decision tree:
    if final_is_anti and not final_is_direct:
        return "A"
    if final_is_direct and not final_is_anti:
        # But check if it's ~isin somewhere else that's the real filter
        if a_hits > 0 and b_hits == 0:
            return "A"
        return "B"
    if a_hits > b_hits:
        return "A"
    if b_hits > a_hits:
        return "B"
    return "other"


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dir-with-Q3_run*.py>", file=sys.stderr)
        return 2
    d = Path(sys.argv[1])
    if not d.is_dir():
        print(f"ERROR: {d} is not a directory", file=sys.stderr)
        return 2
    files = sorted(d.glob("Q3_run*.py"))
    if not files:
        print(f"ERROR: no Q3_run*.py files found in {d}", file=sys.stderr)
        return 2

    rows = []
    for f in files:
        content = f.read_text()
        status = _extract_status(content)
        interp = _classify(content)
        rows.append((f.name, status, interp))

    print(f"{_C.BOLD}Q3 interpretation distribution — {d.name}{_C.RESET}")
    print(f"  {'file':<16}  {'status':<8}  interp")
    print("  " + "─" * 36)
    for name, status, interp in rows:
        sc = _C.GREEN if status == "PASS" else _C.RED
        ic = {"A": _C.GREEN, "B": _C.RED, "other": _C.YELLOW}.get(interp, _C.GREY)
        print(f"  {name:<16}  {sc}{status:<8}{_C.RESET}  {ic}{interp}{_C.RESET}")

    total = len(rows)
    pass_count = sum(1 for _, s, _ in rows if s == "PASS")
    a_count = sum(1 for _, _, i in rows if i == "A")
    b_count = sum(1 for _, _, i in rows if i == "B")
    other_count = sum(1 for _, _, i in rows if i == "other")

    print()
    print(f"{_C.BOLD}Counts{_C.RESET}")
    print(f"  row-count correct:  {pass_count}/{total}")
    print(f"  interpretation A:   {a_count}/{total}")
    print(f"  interpretation B:   {b_count}/{total}")
    if other_count:
        print(f"  unclassified:       {other_count}/{total}")

    # Verdict against ship threshold
    print()
    print(f"{_C.BOLD}Ship threshold verdict{_C.RESET}")
    if pass_count == total and a_count == total:
        print(f"  {_C.GREEN}PRISTINE{_C.RESET} — 10/10 correct + 10/10 interpretation A")
    elif pass_count == total and a_count >= 9:
        print(f"  {_C.GREEN}SHIP IT{_C.RESET} — 10/10 correct + {a_count}/10 A. "
              f"Variance acceptable.")
    elif pass_count == total and a_count <= 8:
        print(f"  {_C.YELLOW}INVESTIGATE{_C.RESET} — 10/10 correct but only {a_count}/10 A. "
              f"Planner may be indifferent between interpretations.")
    elif pass_count < total:
        print(f"  {_C.RED}FAILED{_C.RESET} — only {pass_count}/{total} correct. "
              f"Phase 3 did not close Q3's primary test case.")
    else:
        print(f"  {_C.YELLOW}UNKNOWN{_C.RESET} — mixed signals.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
