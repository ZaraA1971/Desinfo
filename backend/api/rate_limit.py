"""In-memory sliding-window rate limiter (per process)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, *, max_keys: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._max_keys = max_keys

    def allow(self, key: str, limit: int, window_sec: float = 60.0) -> bool:
        now = time.monotonic()
        cutoff = now - window_sec
        with self._lock:
            self._prune_unlocked(cutoff)
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def _prune_unlocked(self, cutoff: float) -> None:
        if len(self._hits) < self._max_keys:
            # light prune: drop empty / stale keys opportunistically
            if len(self._hits) > 256 and len(self._hits) % 64 == 0:
                stale = [k for k, q in self._hits.items() if not q or q[-1] < cutoff]
                for k in stale:
                    del self._hits[k]
            return
        # hard cap: drop oldest-touch keys
        ranked = sorted(
            self._hits.items(),
            key=lambda kv: kv[1][-1] if kv[1] else 0.0,
        )
        for k, _ in ranked[: max(1, len(ranked) // 5)]:
            del self._hits[k]


rate_limiter = RateLimiter()
