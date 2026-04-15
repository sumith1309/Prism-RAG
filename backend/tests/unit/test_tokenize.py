from src.pipelines.retrieval_pipeline import _tokenize


def test_tokenize_splits_on_non_word_and_lowercases():
    assert _tokenize("Hello, World! 2025.") == ["hello", "world", "2025"]


def test_tokenize_handles_empty():
    assert _tokenize("") == []
