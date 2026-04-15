import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # -> backend/
load_dotenv(BASE_DIR / ".env")


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


class Settings:
    def __init__(self) -> None:
        cfg_dir = BASE_DIR / "config"
        data = _load_yaml(cfg_dir / "default.yaml")
        data = _deep_merge(data, _load_yaml(cfg_dir / "_local.yaml"))
        data = _deep_merge(data, _load_yaml(cfg_dir / "local.yaml"))
        if os.environ.get("APP_ENV") == "prod":
            data = _deep_merge(data, _load_yaml(cfg_dir / "prod.yaml"))
        self._data = data

        # env-var overrides (take precedence)
        self.HUGGINGFACEHUB_API_TOKEN = os.environ.get("HUGGINGFACEHUB_API_TOKEN", "")
        self.HF_CHAT_MODEL = os.environ.get("HF_CHAT_MODEL", data["models"]["chat"])
        self.EMBED_MODEL = os.environ.get("EMBED_MODEL", data["models"]["embedding"])
        self.RERANK_MODEL = os.environ.get("RERANK_MODEL", data["models"]["reranker"])

        p = data["paths"]
        self.VECTOR_STORE_DIR = os.environ.get("VECTOR_STORE_DIR", p["vector_store"])
        self.RAW_DIR = os.environ.get("RAW_DIR", p["raw"])
        self.PROCESSED_DIR = os.environ.get("PROCESSED_DIR", p["processed"])
        self.EMBEDDINGS_DIR = os.environ.get("EMBEDDINGS_DIR", p["embeddings"])
        self.REGISTRY_DB = os.environ.get("REGISTRY_DB", p["registry_db"])
        self.SAMPLE_PDF_PATH = os.environ.get("SAMPLE_PDF_PATH", p["sample_pdf"])
        self.LOGS_DIR = os.environ.get("LOGS_DIR", p["logs"])

        i = data["ingestion"]
        self.CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", i["chunk_size"]))
        self.CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", i["chunk_overlap"]))
        self.MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", i["max_upload_mb"]))

        r = data["retrieval"]
        self.DENSE_TOP_K = int(r["dense_top_k"])
        self.BM25_TOP_K = int(r["bm25_top_k"])
        self.RRF_K = int(r["rrf_k"])
        self.RERANK_TOP_N = int(r["rerank_top_n"])
        self.RERANK_CANDIDATES = int(r["rerank_candidates"])
        self.MIN_RERANK_SCORE = float(r["min_rerank_score"])

        g = data["generation"]
        self.MAX_NEW_TOKENS = int(g["max_new_tokens"])
        self.TEMPERATURE = float(g["temperature"])

        q = data.get("qdrant", {})
        self.QDRANT_URL = os.environ.get("QDRANT_URL", q.get("url", "http://localhost:6333"))
        self.QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", q.get("collection", "documents"))
        self.QDRANT_EMBED_DIM = int(os.environ.get("QDRANT_EMBED_DIM", q.get("embed_dim", 384)))

        a = data.get("auth", {})
        self.AUTH_SECRET = os.environ.get("AUTH_SECRET", a.get("secret", "change-me-in-env"))
        self.AUTH_ALGORITHM = os.environ.get("AUTH_ALGORITHM", a.get("algorithm", "HS256"))
        self.AUTH_TOKEN_TTL_MINUTES = int(os.environ.get("AUTH_TOKEN_TTL_MINUTES", a.get("token_ttl_minutes", 720)))

    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    def abs(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    def as_dict(self) -> dict[str, Any]:
        return dict(self._data)


settings = Settings()
