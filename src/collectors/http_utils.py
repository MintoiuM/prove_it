from __future__ import annotations

import json
import random
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from src.io.cache import FileCache, make_cache_key


@dataclass(frozen=True)
class RetryPolicy:
    timeout_seconds: float
    retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    min_interval_seconds: float


class RateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval_seconds = max(0.0, min_interval_seconds)
        self._lock = threading.Lock()
        self._next_ts = 0.0

    def wait(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            if now < self._next_ts:
                time.sleep(self._next_ts - now)
            self._next_ts = time.monotonic() + self.min_interval_seconds


class HttpJsonClient:
    def __init__(
        self,
        retry_policy: RetryPolicy,
        cache: FileCache | None = None,
    ):
        self.retry_policy = retry_policy
        self.cache = cache
        self.rate_limiter = RateLimiter(retry_policy.min_interval_seconds)

    def get_json(
        self,
        endpoint: str,
        params: dict[str, Any],
        use_cache: bool = True,
    ) -> dict[str, Any]:
        cache_key = make_cache_key(endpoint, params)
        if use_cache and self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        query = urllib.parse.urlencode(params, doseq=True)
        url = f"{endpoint}?{query}"
        last_error: Exception | None = None

        for attempt in range(self.retry_policy.retries + 1):
            self.rate_limiter.wait()
            try:
                request = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(
                    request, timeout=self.retry_policy.timeout_seconds
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if use_cache and self.cache is not None:
                    self.cache.set(cache_key, payload)
                return payload
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retry_policy.retries:
                    break
                delay = min(
                    self.retry_policy.backoff_max_seconds,
                    self.retry_policy.backoff_base_seconds * (2 ** attempt),
                )
                jitter = random.uniform(0.0, delay * 0.35)
                time.sleep(delay + jitter)

        raise RuntimeError(f"Request failed after retries: {last_error}") from last_error

