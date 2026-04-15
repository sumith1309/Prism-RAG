"""Integration test: ingest the sample PDF then run a retrieval query.
Requires sentence-transformers + chroma to be installed (slow on cold start)."""
import asyncio
from pathlib import Path

import pytest

from src.config import settings
from src.pipelines.embedding_pipeline import ingest_file
from src.pipelines.retrieval_pipeline import retrieve


@pytest.mark.integration
def test_ingest_and_retrieve_sample():
    sample = settings.abs(settings.SAMPLE_PDF_PATH)
    if not sample.exists():
        pytest.skip("sample PDF missing")

    doc = ingest_file(sample)
    assert doc.chunks > 0

    chunks = asyncio.run(retrieve("How many days of maternity leave?", use_rerank=True, top_k=5))
    assert len(chunks) > 0
    assert any("maternity" in c.text.lower() or "leave" in c.text.lower() for c in chunks)
