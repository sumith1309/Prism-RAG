"""Ingestion pipeline — extracts text, chunks it, embeds dense vectors into Qdrant,
and persists a per-doc BM25 index.

Payload schema stored per chunk in Qdrant:
    doc_id:      str — foreign key to the SQLModel `Document` registry
    filename:    str
    chunk_index: int — stable ordinal used by RRF and citation display
    page:        int — 1-based page number (0 for non-paged formats)
    section:     str — heuristically-assigned section heading
    doc_level:   int — 1..4 RBAC classification (PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED)
    text:        str — the chunk text itself (so retrieval is one hop)
"""

import pickle
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from src.config import settings
from src.core import store
from src.pipelines.loaders import SUPPORTED_EXTS, detect_mime, load_any


_SECTION_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)([A-Z][A-Za-z0-9 &/()\-,]{3,80})\s*$",
    re.MULTILINE,
)
_TOP_HEADING = re.compile(r"^\s*([A-Z][A-Z0-9 &/()\-]{4,60})\s*$", re.MULTILINE)


def _assign_sections(docs: list[LCDocument]) -> list[str]:
    """Best-effort: scan concatenated text once; attach the most recent heading to each chunk."""
    current = ""
    sections: list[str] = []
    for d in docs:
        text = d.page_content
        matches = list(_SECTION_HEADING.finditer(text)) or list(_TOP_HEADING.finditer(text))
        if matches:
            current = matches[-1].group(1).strip().title()
        d.metadata["section"] = current
        sections.append(current)
    return sections


_splitter: Optional[RecursiveCharacterTextSplitter] = None


def _get_splitter() -> RecursiveCharacterTextSplitter:
    global _splitter
    if _splitter is None:
        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
    return _splitter


_embeddings = None
_qdrant: Optional[QdrantClient] = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings
        _embeddings = HuggingFaceEmbeddings(
            model_name=settings.EMBED_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings


def get_qdrant() -> QdrantClient:
    """Lazy singleton Qdrant client, with collection ensured on first use."""
    global _qdrant
    if _qdrant is None:
        client = QdrantClient(url=settings.QDRANT_URL, timeout=30.0)
        if not client.collection_exists(settings.QDRANT_COLLECTION):
            client.create_collection(
                settings.QDRANT_COLLECTION,
                vectors_config=qm.VectorParams(
                    size=settings.QDRANT_EMBED_DIM,
                    distance=qm.Distance.COSINE,
                ),
            )
            # indexes that accelerate our filtered retrieval queries
            client.create_payload_index(
                settings.QDRANT_COLLECTION, field_name="doc_id", field_schema=qm.PayloadSchemaType.KEYWORD
            )
            client.create_payload_index(
                settings.QDRANT_COLLECTION, field_name="doc_level", field_schema=qm.PayloadSchemaType.INTEGER
            )
        _qdrant = client
    return _qdrant


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _save_bm25(doc_id: str, chunk_texts: list[str], chunk_meta: list[dict]) -> None:
    from rank_bm25 import BM25Okapi

    tokenized = [_tokenize(t) for t in chunk_texts]
    bm25 = BM25Okapi(tokenized) if tokenized else None
    bm25_dir = settings.abs(settings.EMBEDDINGS_DIR)
    bm25_dir.mkdir(parents=True, exist_ok=True)
    with open(bm25_dir / f"{doc_id}.pkl", "wb") as f:
        pickle.dump(
            {"bm25": bm25, "texts": chunk_texts, "meta": chunk_meta, "tokenized": tokenized},
            f,
        )


def ingest_file(
    path: Path,
    original_filename: Optional[str] = None,
    doc_level: int = 1,
) -> store.Document:
    """Ingest a file. doc_level defaults to 1 (PUBLIC); the RBAC seeder overrides it."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    doc_id = uuid.uuid4().hex[:12]
    filename = original_filename or path.name

    uploads = settings.abs(settings.RAW_DIR)
    uploads.mkdir(parents=True, exist_ok=True)
    stored_path = uploads / f"{doc_id}{path.suffix.lower()}"
    if stored_path.resolve() != path.resolve():
        stored_path.write_bytes(path.read_bytes())

    raw_docs = load_any(stored_path)
    # Count distinct page numbers across all returned LCDocuments. Works for
    # both 0-indexed (PDF) and 1-indexed (docx/text) loaders without the
    # +1 off-by-one that overcounted by one page on every upload.
    _page_ids = {d.metadata.get("page", 0) for d in raw_docs}
    pages = max(len(_page_ids), 1)
    _assign_sections(raw_docs)

    chunks = _get_splitter().split_documents(raw_docs)
    for i, c in enumerate(chunks):
        c.metadata["doc_id"] = doc_id
        c.metadata["filename"] = filename
        c.metadata["chunk_index"] = i
        c.metadata["doc_level"] = int(doc_level)
        c.metadata.setdefault("page", 0)
        c.metadata.setdefault("section", "")

    if not chunks:
        raise ValueError("No content extracted from document.")

    client = get_qdrant()
    texts = [c.page_content for c in chunks]
    vectors = _get_embeddings().embed_documents(texts)

    points = [
        qm.PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[i],
            payload={
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": i,
                "page": int(c.metadata.get("page", 0) or 0),
                "section": c.metadata.get("section", "") or "",
                "doc_level": int(doc_level),
                "text": c.page_content,
            },
        )
        for i, c in enumerate(chunks)
    ]
    BATCH = 128
    for start in range(0, len(points), BATCH):
        client.upsert(settings.QDRANT_COLLECTION, points=points[start : start + BATCH])

    _save_bm25(
        doc_id,
        texts,
        [
            {
                "doc_id": doc_id,
                "filename": filename,
                "page": int(c.metadata.get("page", 0) or 0),
                "section": c.metadata.get("section", "") or "",
                "chunk_index": i,
                "doc_level": int(doc_level),
            }
            for i, c in enumerate(chunks)
        ],
    )

    sections = sorted({c.metadata.get("section", "") for c in chunks if c.metadata.get("section")})
    doc = store.Document(
        doc_id=doc_id,
        filename=filename,
        mime=detect_mime(stored_path),
        pages=pages,
        chunks=len(chunks),
        sections=",".join(sections),
        doc_level=int(doc_level),
        created_at=datetime.utcnow(),
    )
    store.add_document(doc)
    return doc


def delete_doc(doc_id: str) -> bool:
    doc = store.get_document(doc_id)
    if not doc:
        return False

    try:
        client = get_qdrant()
        client.delete(
            settings.QDRANT_COLLECTION,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[qm.FieldCondition(key="doc_id", match=qm.MatchValue(value=doc_id))]
                )
            ),
        )
    except Exception:
        pass

    bm25_path = settings.abs(settings.EMBEDDINGS_DIR) / f"{doc_id}.pkl"
    if bm25_path.exists():
        bm25_path.unlink()

    uploads = settings.abs(settings.RAW_DIR)
    for p in uploads.glob(f"{doc_id}.*"):
        p.unlink()
    store.delete_document(doc_id)
    return True


def load_sample_if_empty() -> Optional[store.Document]:
    existing = store.list_documents()
    sample_path = settings.abs(settings.SAMPLE_PDF_PATH)
    if existing:
        return None
    if not sample_path.exists():
        return None
    return ingest_file(sample_path, original_filename=sample_path.name, doc_level=1)
