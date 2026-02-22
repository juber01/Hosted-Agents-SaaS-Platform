from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Protocol


_logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    def allow(self, key: str) -> bool:
        raise NotImplementedError


class FixedWindowRateLimiter:
    def __init__(self, requests_per_minute: int) -> None:
        self.requests_per_minute = max(requests_per_minute, 1)
        self._counters: dict[str, tuple[int, int]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now_window = int(time.time() // 60)
        with self._lock:
            window, count = self._counters.get(key, (now_window, 0))
            if window != now_window:
                window, count = now_window, 0
            if count >= self.requests_per_minute:
                self._counters[key] = (window, count)
                return False
            self._counters[key] = (window, count + 1)
            return True


class RedisFixedWindowRateLimiter:
    """Distributed fixed-window limiter backed by Redis."""

    def __init__(
        self,
        requests_per_minute: int,
        redis_url: str,
        key_prefix: str = "saas:ratelimit",
        fail_open: bool = True,
        redis_client: object | None = None,
    ) -> None:
        self.requests_per_minute = max(requests_per_minute, 1)
        self.key_prefix = key_prefix.strip() or "saas:ratelimit"
        self.fail_open = fail_open

        if redis_client is not None:
            self._redis = redis_client
            return

        try:
            import redis
        except ModuleNotFoundError as err:
            raise RuntimeError("Redis rate limiter requires 'redis' package") from err

        self._redis = redis.Redis.from_url(redis_url)

    def allow(self, key: str) -> bool:
        now = time.time()
        now_window = int(now // 60)
        ttl_seconds = max(1, 60 - int(now % 60))
        redis_key = f"{self.key_prefix}:{now_window}:{key}"
        try:
            count = int(self._redis.incr(redis_key))
            if count == 1:
                self._redis.expire(redis_key, ttl_seconds)
            return count <= self.requests_per_minute
        except Exception as err:
            if self.fail_open:
                _logger.warning("redis_rate_limiter_fail_open key=%s err=%s", key, err)
                return True
            raise
