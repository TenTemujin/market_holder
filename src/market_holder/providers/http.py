"""HTTP com limite de taxa e retentativa, só com a stdlib. Um Fetcher por provedor."""

from __future__ import annotations

import asyncio
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Protocol

# Alguns servidores (ex.: FRED) resetam a conexão com User-Agent genérico de script.
USER_AGENT = "Mozilla/5.0 (compatible; market-holder/0.0.1)"
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    pass


class Fetcher(Protocol):
    def fetch(self, url: str) -> bytes: ...


class UrlFetcher:
    def __init__(
        self,
        min_interval_s: float = 0.2,
        retries: int = 3,
        backoff_s: float = 1.0,
        timeout_s: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_s = min_interval_s
        self.retries = retries
        self.backoff_s = backoff_s
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last = float("-inf")

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self.min_interval_s - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()

    def fetch(self, url: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._throttle()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUS:
                    raise FetchError(f"HTTP {e.code} em {url}") from e
                last_error = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_error = e
            self._sleep(self.backoff_s * 2**attempt)
        raise FetchError(f"falhou após {self.retries} tentativas: {url}") from last_error


async def aget(fetcher: Fetcher, url: str) -> bytes:
    return await asyncio.to_thread(fetcher.fetch, url)
