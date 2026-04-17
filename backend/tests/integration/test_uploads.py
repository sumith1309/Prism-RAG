"""Upload visibility assertions — uploader + exec model.

Rules (2026-04-17):
  - Guest uploads   → visible to guest + exec. Hidden from employee, manager.
  - Employee uploads → visible to employee + manager + exec. Hidden from guest.
  - Manager uploads  → visible to manager + exec. Hidden from guest, employee.
  - Executive uploads → whatever they choose (full control).

Uses yield fixtures for guaranteed cleanup — even when assertions fail
mid-test, the uploaded doc is deleted so test artifacts never pollute
the production knowledge base.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Generator

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


def _upload(token: str, filename: str, content: bytes, classification: int | None = None) -> str:
    """Upload a doc and return its doc_id."""
    data = {"classification": str(classification)} if classification is not None else {}
    r = httpx.post(
        f"{BASE}/api/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"files": (filename, io.BytesIO(content), "application/pdf")},
        data=data,
        timeout=120,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body and body[0]["status"] == "ok", body
    return body[0]["doc_id"]


def _delete(doc_id: str) -> None:
    """Delete via exec — guaranteed to work regardless of who uploaded."""
    tok = _login("exec", "exec_pass")
    httpx.delete(f"{BASE}/api/documents/{doc_id}", headers={"Authorization": f"Bearer {tok}"})


@pytest.fixture(scope="module")
def tiny_pdf() -> bytes:
    p = Path(__file__).resolve().parents[3] / "homework-basic" / "data" / "rfc7519_jwt.pdf"
    if not p.exists():
        pytest.skip(f"test requires HW1 PDF at {p}")
    return p.read_bytes()


# ── Yield fixtures: upload + guaranteed cleanup ─────────────────────────────

@pytest.fixture()
def guest_doc(tiny_pdf: bytes) -> Generator[str, None, None]:
    tok = _login("guest", "guest_pass")
    doc_id = _upload(tok, "test_guest_vis.pdf", tiny_pdf)
    yield doc_id
    _delete(doc_id)


@pytest.fixture()
def employee_doc(tiny_pdf: bytes) -> Generator[str, None, None]:
    tok = _login("employee", "employee_pass")
    doc_id = _upload(tok, "test_emp_vis.pdf", tiny_pdf)
    yield doc_id
    _delete(doc_id)


@pytest.fixture()
def manager_doc(tiny_pdf: bytes) -> Generator[str, None, None]:
    tok = _login("manager", "manager_pass")
    doc_id = _upload(tok, "test_mgr_vis.pdf", tiny_pdf)
    yield doc_id
    _delete(doc_id)


@pytest.fixture()
def exec_public_doc(tiny_pdf: bytes) -> Generator[str, None, None]:
    tok = _login("exec", "exec_pass")
    doc_id = _upload(tok, "test_exec_pub.pdf", tiny_pdf, classification=1)
    yield doc_id
    _delete(doc_id)


# ── Tests ───────────────────────────────────────────────────────────────────

def test_guest_upload_visible_to_guest_and_exec_only(guest_doc: str) -> None:
    """Guest uploads → guest sees it, exec sees it, employee/manager don't."""
    doc_id = guest_doc
    assert _doc_visible(_login("guest", "guest_pass"), doc_id), "guest must see own upload"
    assert _doc_visible(_login("exec", "exec_pass"), doc_id), "exec must see guest upload"
    assert not _doc_visible(_login("employee", "employee_pass"), doc_id), "employee must NOT see"
    assert not _doc_visible(_login("manager", "manager_pass"), doc_id), "manager must NOT see"


def test_employee_upload_visible_to_employee_manager_and_exec(employee_doc: str) -> None:
    """Employee uploads → employee, manager, exec see it. Guest doesn't."""
    doc_id = employee_doc
    assert _doc_visible(_login("employee", "employee_pass"), doc_id), "employee must see own upload"
    assert _doc_visible(_login("manager", "manager_pass"), doc_id), "manager must see employee upload"
    assert _doc_visible(_login("exec", "exec_pass"), doc_id), "exec must see employee upload"
    assert not _doc_visible(_login("guest", "guest_pass"), doc_id), "guest must NOT see"


def test_manager_upload_visible_to_manager_and_exec_only(manager_doc: str) -> None:
    """Manager uploads → manager sees it, exec sees it, guest/employee don't."""
    doc_id = manager_doc
    assert _doc_visible(_login("manager", "manager_pass"), doc_id), "manager must see own upload"
    assert _doc_visible(_login("exec", "exec_pass"), doc_id), "exec must see manager upload"
    assert not _doc_visible(_login("guest", "guest_pass"), doc_id), "guest must NOT see"
    assert not _doc_visible(_login("employee", "employee_pass"), doc_id), "employee must NOT see"


def test_exec_upload_full_control(exec_public_doc: str) -> None:
    """Exec uploads at L1 PUBLIC → visible to everyone."""
    doc_id = exec_public_doc
    assert _doc_visible(_login("guest", "guest_pass"), doc_id), "guest must see exec PUBLIC"
    assert _doc_visible(_login("employee", "employee_pass"), doc_id), "employee must see exec PUBLIC"
    assert _doc_visible(_login("manager", "manager_pass"), doc_id), "manager must see exec PUBLIC"
    assert _doc_visible(_login("exec", "exec_pass"), doc_id), "exec must see own upload"
