"""
HW1 — Qdrant CLI RAG tool.

A single-file, teaching-friendly CLI that:
  1. Reads a PDF (default: data/rfc7519_jwt.pdf — RFC 7519, JSON Web Tokens).
  2. Chunks it with configurable size / overlap (defaults 500 / 100).
  3. Builds a dense index in Qdrant (all-MiniLM-L6-v2).
  4. Builds a BM25 index in-memory (rank_bm25).
  5. In an interactive loop, shows dense and BM25 top-k side by side with scores,
     plus an RRF fusion column.
  6. Assembles a grounded RAG prompt with numbered [Source N] citations and
     calls OpenAI gpt-4o-mini (if OPENAI_API_KEY is set) for a final answer.

Designed to match the Session-2 rubric bullet-for-bullet and to be easy to
read end-to-end (no hidden magic, ~300 lines).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import textwrap
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
DEFAULT_PDF = HERE / "data" / "rfc7519_jwt.pdf"
COLLECTION = "rag_cli"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384


# ---------------------------------------------------------------------------
# 1. PDF loading and chunking
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    index: int
    page: int
    text: str


def load_pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(pdf_path))
    pages: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        txt = page.extract_text() or ""
        txt = re.sub(r"[ \t]+", " ", txt)
        txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
        if txt:
            pages.append((i, txt))
    return pages


def chunk_pages(pages: list[tuple[int, str]], chunk_size: int, overlap: int) -> list[Chunk]:
    """Character-based sliding-window chunker that preserves page numbers."""
    assert chunk_size > 0 and 0 <= overlap < chunk_size
    chunks: list[Chunk] = []
    idx = 0
    for page_no, text in pages:
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            piece = text[start:end].strip()
            if len(piece) >= 40:  # skip tiny scraps
                chunks.append(Chunk(index=idx, page=page_no, text=piece))
                idx += 1
            if end == len(text):
                break
            start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# 2. Indexing: dense (Qdrant) + sparse (BM25)
# ---------------------------------------------------------------------------
def build_qdrant(client: QdrantClient, embedder: SentenceTransformer, chunks: list[Chunk]) -> None:
    """Recreate the collection and upload all chunk embeddings."""
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        COLLECTION,
        vectors_config=qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
    )
    texts = [c.text for c in chunks]
    vectors = embedder.encode(texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)
    points = [
        qm.PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[i].tolist(),
            payload={"chunk_index": c.index, "page": c.page, "text": c.text},
        )
        for i, c in enumerate(chunks)
    ]
    # Upload in batches for safety on large docs.
    BATCH = 128
    for i in range(0, len(points), BATCH):
        client.upsert(COLLECTION, points=points[i : i + BATCH])


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def build_bm25(chunks: list[Chunk]) -> BM25Okapi:
    return BM25Okapi([tokenize(c.text) for c in chunks])


# ---------------------------------------------------------------------------
# 3. Retrieval
# ---------------------------------------------------------------------------
@dataclass
class Hit:
    chunk: Chunk
    score: float


def dense_search(client: QdrantClient, embedder: SentenceTransformer, query: str, k: int) -> list[Hit]:
    qvec = embedder.encode([query], normalize_embeddings=True)[0].tolist()
    results = client.query_points(COLLECTION, query=qvec, limit=k).points
    hits: list[Hit] = []
    for r in results:
        p = r.payload or {}
        hits.append(
            Hit(
                chunk=Chunk(index=int(p["chunk_index"]), page=int(p["page"]), text=str(p["text"])),
                score=float(r.score),
            )
        )
    return hits


def bm25_search(bm25: BM25Okapi, chunks: list[Chunk], query: str, k: int) -> list[Hit]:
    scores = bm25.get_scores(tokenize(query))
    # argsort descending
    order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:k]
    return [Hit(chunk=chunks[i], score=float(scores[i])) for i in order if scores[i] > 0]


def rrf_fuse(ranked_lists: list[list[Hit]], k_rrf: int = 60, top_k: int = 3) -> list[Hit]:
    """Reciprocal Rank Fusion — each list contributes 1/(k_rrf + rank)."""
    agg: dict[int, float] = {}
    lookup: dict[int, Chunk] = {}
    for hits in ranked_lists:
        for rank, h in enumerate(hits, start=1):
            agg[h.chunk.index] = agg.get(h.chunk.index, 0.0) + 1.0 / (k_rrf + rank)
            lookup[h.chunk.index] = h.chunk
    ordered = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [Hit(chunk=lookup[i], score=s) for i, s in ordered]


# ---------------------------------------------------------------------------
# 4. Prompt assembly + generation
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a careful assistant answering questions strictly from the provided sources. "
    "Cite sources inline as [Source N]. If the answer is not in the sources, say you don't know."
)


def build_prompt(query: str, hits: list[Hit]) -> str:
    lines = ["Use ONLY the sources below to answer. Cite them inline as [Source N].", ""]
    for n, h in enumerate(hits, start=1):
        snippet = h.chunk.text.strip().replace("\n", " ")
        lines.append(f"[Source {n} | page {h.chunk.page} | chunk #{h.chunk.index}]")
        lines.append(snippet)
        lines.append("")
    lines.append(f"Question: {query}")
    lines.append("Answer (with [Source N] citations):")
    return "\n".join(lines)


def maybe_call_openai(prompt: str) -> str | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # pragma: no cover — demo-friendly
        return f"[OpenAI call failed: {exc}]"


# ---------------------------------------------------------------------------
# 5. Pretty printing
# ---------------------------------------------------------------------------
def _fmt_snippet(text: str, width: int = 90) -> str:
    collapsed = " ".join(text.split())
    return textwrap.shorten(collapsed, width=width, placeholder=" …")


def print_side_by_side(query: str, dense: list[Hit], bm25: list[Hit], fused: list[Hit]) -> None:
    bar = "─" * 78
    print(f"\n{bar}\nQuery: {query}\n{bar}")

    def _block(title: str, hits: list[Hit]) -> None:
        print(f"\n{title}")
        if not hits:
            print("  (no results)")
            return
        for rank, h in enumerate(hits, start=1):
            print(f"  [{rank}] score={h.score:.4f}  page={h.chunk.page}  chunk=#{h.chunk.index}")
            print(f"      {_fmt_snippet(h.chunk.text)}")

    _block("DENSE  (Qdrant · all-MiniLM-L6-v2, cosine)", dense)
    _block("BM25   (rank_bm25, token overlap)", bm25)
    _block("RRF FUSION  (k=60, top-3)", fused)


# ---------------------------------------------------------------------------
# 6. CLI wiring
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HW1 Qdrant CLI — dense + BM25 side-by-side RAG.")
    p.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="Path to source PDF")
    p.add_argument("--chunk", type=int, default=500, help="Chunk size in characters (default 500)")
    p.add_argument("--overlap", type=int, default=100, help="Chunk overlap in characters (default 100)")
    p.add_argument("--top-k", type=int, default=3, help="Results per retriever (default 3)")
    p.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant URL")
    p.add_argument("--rebuild", action="store_true", help="Force re-ingest even if collection exists")
    return p.parse_args()


def main() -> int:
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parent / "backend" / ".env")  # share key with web app if present
    args = parse_args()

    if not args.pdf.exists():
        print(f"ERROR: PDF not found at {args.pdf}", file=sys.stderr)
        print("Run ./setup.sh first to download RFC 7519.", file=sys.stderr)
        return 2

    print(f"Loading PDF: {args.pdf}")
    pages = load_pdf_pages(args.pdf)
    chunks = chunk_pages(pages, args.chunk, args.overlap)
    print(f"  pages={len(pages)}  chunks={len(chunks)}  (size={args.chunk}, overlap={args.overlap})")

    print("Loading embedding model: all-MiniLM-L6-v2 ...")
    embedder = SentenceTransformer(EMBED_MODEL)

    client = QdrantClient(url=args.qdrant_url, timeout=30.0)
    need_build = args.rebuild or not client.collection_exists(COLLECTION)
    if need_build:
        print("Building Qdrant dense index ...")
        build_qdrant(client, embedder, chunks)
    else:
        existing = client.get_collection(COLLECTION).points_count or 0
        if existing != len(chunks):
            print(f"Collection size mismatch ({existing} vs {len(chunks)}) — rebuilding.")
            build_qdrant(client, embedder, chunks)
        else:
            print(f"Reusing existing Qdrant collection '{COLLECTION}' ({existing} points).")

    print("Building BM25 index ...")
    bm25 = build_bm25(chunks)

    gen_available = bool(os.getenv("OPENAI_API_KEY"))
    print(f"\nReady. Generation: {'gpt-4o-mini (OPENAI_API_KEY set)' if gen_available else 'OFF (no key)'}")
    print("Type a question, or 'quit' to exit.\n")

    while True:
        try:
            query = input("? ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in {"quit", "exit", ":q"}:
            break

        dense = dense_search(client, embedder, query, args.top_k)
        sparse = bm25_search(bm25, chunks, query, args.top_k)
        fused = rrf_fuse([dense, sparse], top_k=args.top_k)

        print_side_by_side(query, dense, sparse, fused)

        prompt = build_prompt(query, fused)
        print("\n──── Assembled RAG prompt ────")
        print(prompt)
        print("──────────────────────────────")

        answer = maybe_call_openai(prompt)
        if answer is not None:
            print("\n──── gpt-4o-mini answer ────")
            print(answer)
            print("────────────────────────────\n")
        else:
            print("\n(Set OPENAI_API_KEY in .env to get a generated answer.)\n")

    print("Bye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
