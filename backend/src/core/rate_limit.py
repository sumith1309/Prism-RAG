"""Per-user sliding-window rate limiter (in-memory).

FastAPI dependency. Limits each authenticated user to N calls per window_s
seconds on expensive endpoints. Returns 429 when exceeded.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque, Dict

from fastapi import Depends, HTTPException, status

from src.auth.dependencies import CurrentUser, get_current_user


class _Limiter:
    def __init__(self, max_calls: int, window_s: int) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._buckets: Dict[int, Deque[float]] = {}
        self._lock = Lock()

    def check(self, user_id: int) -> None:
        now = time.time()
        with self._lock:
            dq = self._buckets.setdefault(user_id, deque())
            while dq and now - dq[0] > self.window_s:
                dq.popleft()
            if len(dq) >= self.max_calls:
                retry_after = int(self.window_s - (now - dq[0]))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        f"Rate limit exceeded: max {self.max_calls} per "
                        f"{self.window_s}s. Retry in ~{retry_after}s."
                    ),
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            dq.append(now)


_chat_limiter = _Limiter(max_calls=60, window_s=60)  # 60 chats/min/user
_upload_limiter = _Limiter(max_calls=30, window_s=60)  # 30 uploads/min/user


def chat_rate_limit(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    _chat_limiter.check(user.id)
    return user


def upload_rate_limit(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    _upload_limiter.check(user.id)
    return user
