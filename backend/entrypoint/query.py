"""CLI query script for smoke-testing retrieval + generation without the server.

Usage:
    python -m entrypoint.query "How many days of maternity leave?"
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipelines.generation_pipeline import stream_answer
from src.pipelines.retrieval_pipeline import retrieve


async def run(query: str) -> None:
    chunks = await retrieve(query=query, use_hyde=False, use_rerank=True, top_k=5)
    print(f"\nRetrieved {len(chunks)} chunk(s):")
    for c in chunks:
        rr = f"{c.rerank_score:.3f}" if c.rerank_score is not None else "-"
        print(f"  [{c.source_index}] {c.filename} p.{c.page} ({c.section})  rrf={c.rrf_score:.4f}  rerank={rr}")
        print(f"      {c.text[:120]}...")

    print("\nAnswer:")
    async for token in stream_answer(query, chunks):
        sys.stdout.write(token)
        sys.stdout.flush()
    print()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m entrypoint.query '<question>'")
        raise SystemExit(1)
    asyncio.run(run(" ".join(sys.argv[1:])))


if __name__ == "__main__":
    main()
