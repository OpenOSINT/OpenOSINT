"""
OpenOSINT Cloud — per-tenant burst limiter for platform-pool tool calls.

Burst smoothing only. The real spend cap is the atomic Postgres credit
decrement in cloud/db.py (dyno-safe, durable). This limiter exists so one
tenant can't hammer a shared platform key (Shodan, IP2Location) with
rapid-fire requests within their credit balance.

BurstLimiter is a small Protocol so the in-process implementation can be
swapped for a Redis/Postgres-backed one later without touching call sites.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Protocol

from cloud.config import (
    PLATFORM_BURST_MAX_CALLS,
    PLATFORM_BURST_WINDOW_SECS,
    WAITLIST_RATE_MAX_CALLS,
    WAITLIST_RATE_WINDOW_SECS,
)


class BurstLimiter(Protocol):
    def allow(self, key: str) -> bool:
        """Return True if a call under `key` is allowed right now."""
        ...


class InProcessSlidingWindowLimiter:
    """Sliding-window limiter keyed by an arbitrary string (e.g. "api_key:tool").

    Not durable across dyno restarts and not shared across multiple dynos —
    acceptable because this is burst smoothing, not the spend cap.
    """

    def __init__(self, window_secs: float, max_calls: int, max_buckets: int = 10_000) -> None:
        self._window_secs = window_secs
        self._max_calls = max_calls
        self._max_buckets = max_buckets
        self._buckets: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_buckets:
                # ponytail: fail-open under bucket-table pressure — this is
                # burst smoothing, not the spend cap, so refusing service to
                # a new tenant is worse than a missed rate-limit window.
                return True
            bucket = deque()
            self._buckets[key] = bucket
        while bucket and now - bucket[0] > self._window_secs:
            bucket.popleft()
        if len(bucket) >= self._max_calls:
            return False
        bucket.append(now)
        return True


# Shared instance guarding all platform-pool tool calls, tunable via env vars
# (see cloud/config.PLATFORM_BURST_WINDOW_SECS / PLATFORM_BURST_MAX_CALLS).
platform_pool_limiter: BurstLimiter = InProcessSlidingWindowLimiter(
    window_secs=PLATFORM_BURST_WINDOW_SECS,
    max_calls=PLATFORM_BURST_MAX_CALLS,
)

# Shared instance guarding the public, unauthenticated POST /v1/waitlist route.
# Keyed by client IP (see cloud/routes/waitlist.py) since there's no api_key
# to key on yet.
waitlist_limiter: BurstLimiter = InProcessSlidingWindowLimiter(
    window_secs=WAITLIST_RATE_WINDOW_SECS,
    max_calls=WAITLIST_RATE_MAX_CALLS,
)
