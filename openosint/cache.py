"""
Lightweight TTL-based async function cache.

Provides an ``@cached(ttl=N)`` decorator for async functions.
Results are stored in-memory with expiry timestamps. No external
dependencies — pure Python stdlib.

Usage::

    from openosint.cache import cached

    @cached(ttl=300)
    async def fetch_shodan(ip: str) -> dict:
        ...
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AsyncTTLCache:
    """
    In-memory TTL cache for async functions.

    Stores results in a dict keyed by (function_name, args_hash).
    Entries expire after ``ttl`` seconds.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        return f"{func_name}:{hash(args)}:{hash(frozenset(kwargs.items()))}"

    async def get_or_compute(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Any],
    ) -> Any:
        now = time.monotonic()
        async with self._lock:
            cached = self._store.get(key)
            if cached is not None:
                ts, value = cached
                if now - ts < ttl:
                    logger.debug("Cache HIT for %s (age=%.1fs)", key, now - ts)
                    return value
                del self._store[key]

        # Compute outside the lock to avoid holding it during I/O
        value = await factory()

        async with self._lock:
            self._store[key] = (time.monotonic(), value)
        return value

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
        logger.debug("Cache cleared")

    @property
    def size(self) -> int:
        return len(self._store)


# Module-level singleton
_cache = AsyncTTLCache()


def clear_cache() -> None:
    """Clear all cached results."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(_cache.clear())
            return
    except RuntimeError:
        pass
    # Fallback for sync contexts
    asyncio.run(_cache.clear())


def cached(ttl: float = 300.0) -> Callable:
    """
    Decorator that caches the return value of an async function.

    Parameters
    ----------
    ttl:
        Time-to-live in seconds (default: 300 = 5 minutes).

    Usage::

        @cached(ttl=600)
        async def fetch_api(target: str) -> dict:
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _cache._make_key(func.__qualname__, args, kwargs)
            return await _cache.get_or_compute(
                key,
                ttl=ttl,
                factory=functools.partial(func, *args, **kwargs),
            )

        return wrapper

    return decorator
