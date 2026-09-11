"""
app/auth/rate_limiter.py

In-memory sliding-window rate limiter to safeguard authentication endpoints against
brute-force attacks, credential stuffing, and account enumeration attempts.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List
from fastapi import HTTPException, status


class SlidingWindowLimiter:
    def __init__(self):
        # Key -> list of event timestamps
        self._events: Dict[str, List[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int, window_seconds: float) -> tuple[bool, int]:
        now = time.time()
        cutoff = now - window_seconds
        # Evict timestamps outside the window
        timestamps = [t for t in self._events[key] if t > cutoff]
        self._events[key] = timestamps

        if len(timestamps) >= max_requests:
            retry_after = int(window_seconds - (now - timestamps[0])) + 1
            return False, max(1, retry_after)

        return True, 0

    def record(self, key: str) -> None:
        self._events[key].append(time.time())

    def reset(self, key: str) -> None:
        if key in self._events:
            del self._events[key]


auth_limiter = SlidingWindowLimiter()


def enforce_rate_limit(key: str, max_attempts: int, window_seconds: float, error_detail: str) -> None:
    allowed, retry_after = auth_limiter.is_allowed(key, max_attempts, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{error_detail} Please try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
