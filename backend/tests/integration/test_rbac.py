"""End-to-end RBAC assertions.

Runs against the real Qdrant instance and the seeded corpus. For every
(role, query) pair, we verify:
  1. No chunk with doc_level > user.level is ever returned.
  2. Boundary queries (e.g. ``manager`` asking for a RESTRICTED security incident)
     do NOT return the restricted doc.
  3. Full-clearance queries (e.g. ``executive`` asking the same) DO.

Prereqs: Qdrant running, ``python -m entrypoint.seed --wipe`` executed, no
HTTP server needed — we exercise the retrieval pipeline directly.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.pipelines.retrieval_pipeline import retrieve  # noqa: E402


ROLES = {
    "guest": 1,
    "employee": 2,
    "manager": 3,
    "executive": 4,
}


async def _retrieve(query: str, level: int, k: int = 5):
    return await retrieve(query=query, top_k=k, use_rerank=False, max_doc_level=level)


def _filenames(chunks) -> set[str]:
    return {c.filename for c in chunks}


# --- invariant 1 ----------------------------------------------------------
# No chunk above clearance is ever returned, for any role × any query.


@pytest.mark.parametrize(
    "query",
    [
        "What training is mandatory?",
        "What is the on-call rotation?",
        "Summarize Q4 revenue",
        "What is the CEO salary?",
        "What was the November security incident?",
    ],
)
@pytest.mark.parametrize("role,level", list(ROLES.items()))
def test_no_chunk_above_clearance(role: str, level: int, query: str) -> None:
    chunks = asyncio.run(_retrieve(query, level))
    for c in chunks:
        # doc_level isn't on RetrievedChunk; derive from filename mapping instead.
        # This is a belt-and-braces test: every returned filename must map to
        # level <= user.level per the FILENAME_LEVEL table from the seeder.
        assert _level_for(c.filename) <= level, (
            f"[{role} L{level}] leak: {c.filename} (level {_level_for(c.filename)}) "
            f"returned for query {query!r}"
        )


# --- invariant 2 ----------------------------------------------------------
# Boundary cases — the specific demo-script assertions.


def test_guest_cannot_see_salary() -> None:
    chunks = asyncio.run(_retrieve("What is the CEO salary?", 1))
    assert "TechNova_Salary_Structure.pdf" not in _filenames(chunks)


def test_employee_cannot_see_q4_revenue_doc() -> None:
    chunks = asyncio.run(_retrieve("Summarize Q4 revenue numbers", 2))
    assert "TechNova_Q4_Financial_Report.pdf" not in _filenames(chunks)


def test_manager_cannot_see_security_incident() -> None:
    chunks = asyncio.run(_retrieve("What was the November security incident?", 3))
    assert "TechNova_Security_Incident_Report.pdf" not in _filenames(chunks)
    assert "TechNova_Board_Minutes_Q4.pdf" not in _filenames(chunks)


# --- invariant 3 ----------------------------------------------------------
# Full-clearance users DO get the expected doc.


def test_manager_gets_q4_financials() -> None:
    chunks = asyncio.run(_retrieve("Summarize Q4 revenue numbers", 3))
    assert "TechNova_Q4_Financial_Report.pdf" in _filenames(chunks)


def test_executive_gets_security_incident() -> None:
    chunks = asyncio.run(_retrieve("What was the November security incident?", 4))
    assert "TechNova_Security_Incident_Report.pdf" in _filenames(chunks)


# --- helpers --------------------------------------------------------------

_LEVEL_BY_FILENAME: dict[str, int] = {
    "TechNova_Training_Compliance.pdf": 1,
    "TechNova_IT_Asset_Policy.pdf": 2,
    "TechNova_OnCall_Runbook.pdf": 2,
    "TechNova_Platform_Architecture.pdf": 2,
    "TechNova_Product_Roadmap_2026.pdf": 3,
    "TechNova_Q4_Financial_Report.pdf": 3,
    "TechNova_Vendor_Contracts.pdf": 3,
    "TechNova_Board_Minutes_Q4.pdf": 4,
    "TechNova_Salary_Structure.pdf": 4,
    "TechNova_Security_Incident_Report.pdf": 4,
}


def _level_for(filename: str) -> int:
    return _LEVEL_BY_FILENAME.get(filename, 1)
