from __future__ import annotations

import time
from threading import Lock


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
