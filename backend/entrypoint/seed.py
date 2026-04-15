"""Seed the RBAC demo: 4 users + 10 classified TechNova PDFs.

Reads each PDF's first page, looks for a classification header
(PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED), maps it to a level,
and ingests with ``doc_level`` set. Falls back to a filename-based
mapping if no header is present (keeps the demo deterministic).

Usage:
    python -m entrypoint.seed                       # seed users + all 10 PDFs
    python -m entrypoint.seed --users-only          # skip ingestion
    python -m entrypoint.seed --wipe                # clear everything first
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader
from qdrant_client.http import models as qm

from src.auth.security import hash_password
from src.config import settings
from src.core import models, store
from src.pipelines.embedding_pipeline import get_qdrant, ingest_file


SEED_USERS = [
    {"username": "guest", "password": "guest_pass", "role": "guest", "level": 1, "title": "Intern / Guest"},
    {"username": "employee", "password": "employee_pass", "role": "employee", "level": 2, "title": "Employee"},
    {"username": "manager", "password": "manager_pass", "role": "manager", "level": 3, "title": "Manager"},
    {"username": "exec", "password": "exec_pass", "role": "executive", "level": 4, "title": "Executive"},
]


# Fallback mapping if the PDF has no classification header.
FILENAME_LEVEL = {
    "TechNova_Training_Compliance.pdf": 1,  # PUBLIC
    "TechNova_IT_Asset_Policy.pdf": 2,  # INTERNAL
    "TechNova_OnCall_Runbook.pdf": 2,  # INTERNAL
    "TechNova_Platform_Architecture.pdf": 2,  # INTERNAL
    "TechNova_Product_Roadmap_2026.pdf": 3,  # CONFIDENTIAL
    "TechNova_Q4_Financial_Report.pdf": 3,  # CONFIDENTIAL
    "TechNova_Vendor_Contracts.pdf": 3,  # CONFIDENTIAL
    "TechNova_Board_Minutes_Q4.pdf": 4,  # RESTRICTED
    "TechNova_Salary_Structure.pdf": 4,  # RESTRICTED
    "TechNova_Security_Incident_Report.pdf": 4,  # RESTRICTED
}

LABEL_TO_LEVEL = {"PUBLIC": 1, "INTERNAL": 2, "CONFIDENTIAL": 3, "RESTRICTED": 4}
LEVEL_TO_LABEL = {v: k for k, v in LABEL_TO_LEVEL.items()}

_LABEL_RE = re.compile(
    r"\b(?:CLASSIFICATION|CLASSIFIED|LEVEL)\s*[:\-]?\s*(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)\b",
    re.IGNORECASE,
)
_BARE_LABEL_RE = re.compile(r"\b(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)\b")


def detect_doc_level(pdf_path: Path) -> int:
    """Prefer an explicit 'Classification: X' header on the first page."""
    try:
        reader = PdfReader(str(pdf_path))
        first = (reader.pages[0].extract_text() or "")[:800]
    except Exception:
        first = ""
    m = _LABEL_RE.search(first)
    if m:
        return LABEL_TO_LEVEL[m.group(1).upper()]
    m = _BARE_LABEL_RE.search(first)
    if m:
        return LABEL_TO_LEVEL[m.group(1).upper()]
    return FILENAME_LEVEL.get(pdf_path.name, 1)


def seed_users() -> None:
    print("==> Seeding users")
    for u in SEED_USERS:
        user = models.User(
            username=u["username"],
            password_hash=hash_password(u["password"]),
            role=u["role"],
            level=int(u["level"]),
            title=u["title"],
        )
        models.upsert_user(user)
        print(f"   {u['username']:10s}  level={u['level']}  role={u['role']}")


def wipe_all() -> None:
    print("==> Wiping existing documents, Qdrant collection, BM25 indexes, and audit log")
    try:
        client = get_qdrant()
        if client.collection_exists(settings.QDRANT_COLLECTION):
            client.delete_collection(settings.QDRANT_COLLECTION)
    except Exception as e:
        print(f"   (qdrant wipe: {e})")

    # Reset cached client so the next get_qdrant() recreates the collection.
    import src.pipelines.embedding_pipeline as ep
    ep._qdrant = None

    embeds = settings.abs(settings.EMBEDDINGS_DIR)
    for p in embeds.glob("*.pkl"):
        p.unlink()

    from sqlmodel import Session, delete

    from src.core.store import _get_engine

    engine = _get_engine()
    with Session(engine) as s:
        s.exec(delete(store.Document))
        s.exec(delete(models.AuditLog))
        s.commit()


def seed_documents(corpus_dir: Path) -> None:
    print(f"==> Ingesting PDFs from {corpus_dir}")
    if not corpus_dir.exists():
        raise SystemExit(f"Corpus directory not found: {corpus_dir}")

    pdfs = sorted(corpus_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {corpus_dir}")

    total_chunks = 0
    for pdf in pdfs:
        level = detect_doc_level(pdf)
        label = LEVEL_TO_LABEL[level]
        print(f"   [{label:12s} · L{level}]  {pdf.name}")
        doc = ingest_file(pdf, original_filename=pdf.name, doc_level=level)
        total_chunks += doc.chunks
    print(f"==> Ingested {len(pdfs)} PDFs, {total_chunks} total chunks")

    client = get_qdrant()
    info = client.get_collection(settings.QDRANT_COLLECTION)
    print(f"    Qdrant collection '{settings.QDRANT_COLLECTION}' now holds {info.points_count} points")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed RBAC demo (users + classified PDFs)")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "sir_documents",
        help="Directory of TechNova PDFs (default: ../sir_documents)",
    )
    parser.add_argument("--users-only", action="store_true")
    parser.add_argument("--wipe", action="store_true", help="Clear docs + audit log before seeding")
    args = parser.parse_args()

    if args.wipe:
        wipe_all()

    seed_users()

    if args.users_only:
        return

    seed_documents(args.corpus)
    print("\nDone.")


if __name__ == "__main__":
    main()
