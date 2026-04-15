"""In-memory per-user LRU cache for identical chat queries.

Key = sha1(user_id | level | query | doc_ids | settings). TTL = 10 minutes.
Cached responses are still audited (with ``cached=True``) so analytics stays
honest about traffic volume.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Optional

_CACHE_MAX = 512
_CACHE_TTL_S = 10 * 60  # 10 minutes

_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_lock = Lock()


def _key(user_id: int, level: int, query: str, doc_ids: list[str], settings: dict) -> str:
    payload = json.dumps(
        {
            "u": int(user_id),
            "l": int(level),
            "q": query.strip(),
            "d": sorted(doc_ids or []),
            "s": settings or {},
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode()).hexdigest()


def get(user_id: int, level: int, query: str, doc_ids: list[str], settings: dict) -> Optional[dict]:
    k = _key(user_id, level, query, doc_ids, settings)
    with _lock:
        entry = _cache.get(k)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > _CACHE_TTL_S:
            _cache.pop(k, None)
            return None
        _cache.move_to_end(k)
        return value


def put(
    user_id: int,
    level: int,
    query: str,
    doc_ids: list[str],
    settings: dict,
    value: dict,
) -> None:
    k = _key(user_id, level, query, doc_ids, settings)
    with _lock:
        _cache[k] = (time.time(), value)
        _cache.move_to_end(k)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def stats() -> dict[str, Any]:
    with _lock:
        return {"size": len(_cache), "max": _CACHE_MAX, "ttl_s": _CACHE_TTL_S}


def clear() -> None:
    with _lock:
        _cache.clear()
