"""Upload clearance-cap assertions.

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


def test_guest_upload_default_classification_succeeds(tiny_pdf: bytes) -> None:
    """Guest (L1) uploads with default classification → stored as PUBLIC (level 1)."""
    tok = _login("guest", "guest_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {tok}"},
        files={"files": ("test_guest_default.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body and body[0]["status"] == "ok"
    doc_id = body[0]["doc_id"]

    # Verify it's visible to guest and classified as PUBLIC.
    docs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {tok}"}).json()
    found = [d for d in docs if d["doc_id"] == doc_id]
    assert found and found[0]["classification"] == "PUBLIC", found

    # cleanup — delete via manager
    mtok = _login("manager", "manager_pass")
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {mtok}"})


def test_guest_upload_above_clearance_rejected(tiny_pdf: bytes) -> None:
    """Guest (L1) tries classification=2 → 400."""
    tok = _login("guest", "guest_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {tok}"},
        files={"files": ("test_guest_bad.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        data={"classification": "2"},
        timeout=60,
    )
    assert r.status_code == 400, r.text


def test_manager_upload_at_confidential_stored_correctly(tiny_pdf: bytes) -> None:
    """Manager (L3) uploads classification=3 → stored as CONFIDENTIAL; not visible to L2."""
    mtok = _login("manager", "manager_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {mtok}"},
        files={"files": ("test_manager_conf.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        data={"classification": "3"},
        timeout=120,
    )
    assert r.status_code == 200, r.text
    doc_id = r.json()[0]["doc_id"]

    # Visible to manager.
    mdocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {mtok}"}).json()
    assert any(d["doc_id"] == doc_id and d["classification"] == "CONFIDENTIAL" for d in mdocs)

    # NOT visible to employee.
    etok = _login("employee", "employee_pass")
    edocs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {etok}"}).json()
    assert all(d["doc_id"] != doc_id for d in edocs)

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {mtok}"})
