"""Upload visibility-escalation assertions.

With the review-first model (2026-04-17):
  - Guest/Manager uploads → RESTRICTED (L4, exec only)
  - Employee uploads → CONFIDENTIAL (L3, manager + exec)
  - Executive uploads → whatever they choose

Prereqs: backend running on :8765 with seeded users. The tests use the real
HTTP API end-to-end (httpx) so the FastAPI dependency + form validation is
exercised.
"""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest

BASE = "http://127.0.0.1:8765"


def _login(username: str, password: str) -> str:
    r = httpx.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def tiny_pdf() -> bytes:
    """Use the already-downloaded HW1 RFC PDF as a harmless test payload."""
    p = Path(__file__).resolve().parents[3] / "homework-basic" / "data" / "rfc7519_jwt.pdf"
    if not p.exists():
        pytest.skip(f"test requires HW1 PDF at {p}")
    return p.read_bytes()


def test_guest_upload_escalated_to_restricted(tiny_pdf: bytes) -> None:
    """Guest (L1) uploads → escalated to RESTRICTED (L4), only exec can see."""
    tok = _login("guest", "guest_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {tok}"},
        files={"files": ("test_guest_esc.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body and body[0]["status"] == "ok"
    doc_id = body[0]["doc_id"]

    # NOT visible to guest (it's L4, they're L1).
    gdocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {tok}"}).json()
    assert all(d["doc_id"] != doc_id for d in gdocs), "guest should NOT see their own escalated doc"

    # Visible to exec as RESTRICTED.
    etok = _login("exec", "exec_pass")
    edocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {etok}"}).json()
    found = [d for d in edocs if d["doc_id"] == doc_id]
    assert found and found[0]["classification"] == "RESTRICTED", f"exec should see RESTRICTED, got {found}"

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {etok}"})


def test_guest_classification_param_ignored(tiny_pdf: bytes) -> None:
    """Guest passes classification=1 explicitly → ignored, still escalated to L4."""
    tok = _login("guest", "guest_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {tok}"},
        files={"files": ("test_guest_ignored.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        data={"classification": "1"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()[0]["doc_id"]

    # Still NOT visible to guest.
    gdocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {tok}"}).json()
    assert all(d["doc_id"] != doc_id for d in gdocs)

    # cleanup
    etok = _login("exec", "exec_pass")
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {etok}"})


def test_manager_upload_escalated_to_restricted(tiny_pdf: bytes) -> None:
    """Manager (L3) uploads → escalated to RESTRICTED (L4), only exec sees."""
    mtok = _login("manager", "manager_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {mtok}"},
        files={"files": ("test_mgr_esc.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        data={"classification": "3"},  # ignored — escalated anyway
        timeout=120,
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()[0]["doc_id"]

    # NOT visible to manager (L4 > L3).
    mdocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {mtok}"}).json()
    assert all(d["doc_id"] != doc_id for d in mdocs), "manager should NOT see escalated doc"

    # Visible to exec.
    etok = _login("exec", "exec_pass")
    edocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {etok}"}).json()
    assert any(d["doc_id"] == doc_id and d["classification"] == "RESTRICTED" for d in edocs)

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {etok}"})


def test_employee_upload_escalated_to_confidential(tiny_pdf: bytes) -> None:
    """Employee (L2) uploads → escalated to CONFIDENTIAL (L3), manager + exec see."""
    etok = _login("employee", "employee_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {etok}"},
        files={"files": ("test_emp_esc.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()[0]["doc_id"]

    # NOT visible to employee (L3 > L2).
    edocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {etok}"}).json()
    assert all(d["doc_id"] != doc_id for d in edocs), "employee should NOT see escalated doc"

    # Visible to manager (L3).
    mtok = _login("manager", "manager_pass")
    mdocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {mtok}"}).json()
    assert any(d["doc_id"] == doc_id and d["classification"] == "CONFIDENTIAL" for d in mdocs)

    # Visible to exec.
    xtok = _login("exec", "exec_pass")
    xdocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {xtok}"}).json()
    assert any(d["doc_id"] == doc_id for d in xdocs)

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {xtok}"})
