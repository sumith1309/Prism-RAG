"""Unit test: RRF fusion correctness."""
import pytest

from src.pipelines.retrieval_pipeline import _rrf_fuse


def test_rrf_fuse_merges_and_ranks():
    dense = [("a", {"doc_id": "d1", "chunk_index": 0}, 0.9), ("b", {"doc_id": "d1", "chunk_index": 1}, 0.8)]
    bm25 = [("b", {"doc_id": "d1", "chunk_index": 1}, 5.0), ("c", {"doc_id": "d1", "chunk_index": 2}, 3.0)]

    fused = _rrf_fuse(dense, bm25, k=60)

    texts = [t for t, _m, _s in fused]
    # b appears in both and should be ranked first
    assert texts[0] == "b"
    # a and c both appear once
    assert set(texts) == {"a", "b", "c"}


def test_rrf_fuse_empty_inputs():
    assert _rrf_fuse([], [], k=60) == []
