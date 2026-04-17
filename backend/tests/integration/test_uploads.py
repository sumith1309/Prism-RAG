"""Upload visibility assertions — uploader + exec model.

Rules (2026-04-17):
  - Guest uploads   → visible to guest + exec. Hidden from employee, manager.
  - Employee uploads → visible to employee + exec. Hidden from guest, manager.
  - Manager uploads  → visible to manager + exec. Hidden from guest, employee.
  - Executive uploads → whatever they choose (full control).

Mechanism: doc_level stays at uploader's own level (so they can see it).
disabled_for_roles is auto-set to block all other non-exec roles.

Prereqs: backend running on :8765 with seeded users.
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


def _doc_visible(token: str, doc_id: str) -> bool:
    docs = httpx.get(f"{BASE}/api/documents", headers={"Authorization": f"Bearer {token}"}).json()
    return any(d["doc_id"] == doc_id for d in docs)


@pytest.fixture(scope="module")
def tiny_pdf() -> bytes:
    p = Path(__file__).resolve().parents[3] / "homework-basic" / "data" / "rfc7519_jwt.pdf"
    if not p.exists():
        pytest.skip(f"test requires HW1 PDF at {p}")
    return p.read_bytes()


def test_guest_upload_visible_to_guest_and_exec_only(tiny_pdf: bytes) -> None:
    """Guest uploads → guest sees it, exec sees it, employee/manager don't."""
    gtok = _login("guest", "guest_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {gtok}"},
        files={"files": ("test_guest.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        timeout=120,
    )
    assert r.status_code == 200
    doc_id = r.json()[0]["doc_id"]

    # Guest sees their own doc.
    assert _doc_visible(gtok, doc_id), "guest must see their own upload"

    # Exec sees it.
    xtok = _login("exec", "exec_pass")
    assert _doc_visible(xtok, doc_id), "exec must see guest's upload"

    # Employee does NOT see it.
    etok = _login("employee", "employee_pass")
    assert not _doc_visible(etok, doc_id), "employee must NOT see guest's upload"

    # Manager does NOT see it.
    mtok = _login("manager", "manager_pass")
    assert not _doc_visible(mtok, doc_id), "manager must NOT see guest's upload"

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {xtok}"})


def test_employee_upload_visible_to_employee_and_exec_only(tiny_pdf: bytes) -> None:
    """Employee uploads → employee sees it, exec sees it, guest/manager don't."""
    etok = _login("employee", "employee_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {etok}"},
        files={"files": ("test_emp.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        timeout=120,
    )
    assert r.status_code == 200
    doc_id = r.json()[0]["doc_id"]

    # Employee sees their own doc.
    assert _doc_visible(etok, doc_id), "employee must see their own upload"

    # Exec sees it.
    xtok = _login("exec", "exec_pass")
    assert _doc_visible(xtok, doc_id), "exec must see employee's upload"

    # Guest does NOT see it.
    gtok = _login("guest", "guest_pass")
    assert not _doc_visible(gtok, doc_id), "guest must NOT see employee's upload"

    # Manager does NOT see it.
    mtok = _login("manager", "manager_pass")
    assert not _doc_visible(mtok, doc_id), "manager must NOT see employee's upload"

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {xtok}"})


def test_manager_upload_visible_to_manager_and_exec_only(tiny_pdf: bytes) -> None:
    """Manager uploads → manager sees it, exec sees it, guest/employee don't."""
    mtok = _login("manager", "manager_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {mtok}"},
        files={"files": ("test_mgr.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        timeout=120,
    )
    assert r.status_code == 200
    doc_id = r.json()[0]["doc_id"]

    # Manager sees their own doc.
    assert _doc_visible(mtok, doc_id), "manager must see their own upload"

    # Exec sees it.
    xtok = _login("exec", "exec_pass")
    assert _doc_visible(xtok, doc_id), "exec must see manager's upload"

    # Guest does NOT.
    gtok = _login("guest", "guest_pass")
    assert not _doc_visible(gtok, doc_id), "guest must NOT see manager's upload"

    # Employee does NOT.
    etok = _login("employee", "employee_pass")
    assert not _doc_visible(etok, doc_id), "employee must NOT see manager's upload"

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {xtok}"})


def test_exec_upload_full_control(tiny_pdf: bytes) -> None:
    """Exec uploads at L1 PUBLIC → visible to everyone (no auto-hide)."""
    xtok = _login("exec", "exec_pass")
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {xtok}"},
        files={"files": ("test_exec.pdf", io.BytesIO(tiny_pdf), "application/pdf")},
        data={"classification": "1"},
        timeout=120,
    )
    assert r.status_code == 200
    doc_id = r.json()[0]["doc_id"]

    # Everyone sees it (L1 PUBLIC, no disabled_for_roles).
    gtok = _login("guest", "guest_pass")
    assert _doc_visible(gtok, doc_id), "guest must see exec's PUBLIC upload"

    etok = _login("employee", "employee_pass")
    assert _doc_visible(etok, doc_id), "employee must see exec's PUBLIC upload"

    # cleanup
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {xtok}"})
