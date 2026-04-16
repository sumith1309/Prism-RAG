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


def bust_for_doc(doc_id: str) -> int:
    """Remove cached entries whose stored response cited ``doc_id``.

    Called from /documents PATCH visibility and /documents DELETE so a
    reclassified or removed document never replays a stale answer that
    includes its (now-different-clearance / now-deleted) content. Pure
    correctness fix — without this, a guest could see a cached answer
    from before exec promoted a doc to RESTRICTED.

    Returns the number of cache entries removed.
    """
    if not doc_id:
        return 0
    removed = 0
    with _lock:
        keys_to_remove = []
        for k, (_, value) in _cache.items():
            cited = value.get("cited_doc_ids") or []
            if doc_id in cited:
                keys_to_remove.append(k)
        for k in keys_to_remove:
            _cache.pop(k, None)
            removed += 1
    return removed


def bust_all() -> int:
    """Nuclear option — drop everything. Used when the change is
    corpus-wide (e.g., re-ingestion, mass delete) and per-doc busting
    would be slower than just clearing.
    """
    with _lock:
        n = len(_cache)
        _cache.clear()
        return n
