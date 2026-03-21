import os
import random
import threading
import time

from curl_cffi import requests


class _RateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self._rps = max(0.1, requests_per_second)
        self._min_interval = 1.0 / self._rps
        self._lock = threading.Lock()
        self._last_request_at = 0.0

    def wait_turn(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()


class _CircuitBreaker:
    def __init__(self, threshold: int, open_seconds: int) -> None:
        self._threshold = max(1, threshold)
        self._open_seconds = max(5, open_seconds)
        self._consecutive_failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def remaining_open_seconds(self) -> float:
        with self._lock:
            now = time.monotonic()
            return max(0.0, self._open_until - now)

    def success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._open_until = time.monotonic() + self._open_seconds


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_RPS = float(os.getenv("ML_MAX_RPS", "0.35"))
_MAX_RETRIES = int(os.getenv("ML_MAX_RETRIES", "3"))
_BACKOFF_BASE_SECONDS = float(os.getenv("ML_BACKOFF_BASE_SECONDS", "2.0"))
_BLOCK_THRESHOLD = int(os.getenv("ML_CIRCUIT_THRESHOLD", "3"))
_CIRCUIT_SECONDS = int(os.getenv("ML_CIRCUIT_SECONDS", "180"))

_session = requests.Session()
_limiter = _RateLimiter(_RPS)
_breaker = _CircuitBreaker(_BLOCK_THRESHOLD, _CIRCUIT_SECONDS)


def _looks_blocked(response: requests.Response) -> bool:
    if response.status_code in {403, 429, 503}:
        return True

    url = (response.url or "").lower()
    text = (response.text or "").lower()
    block_markers = [
        "captcha",
        "account-verification",
        "/login",
        "denied",
        "access denied",
    ]
    return any(marker in url or marker in text for marker in block_markers)


def resilient_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: int = 15,
    allow_redirects: bool = True,
    stream: bool = False,
    max_retries: int | None = None,
    wait_for_circuit: bool = True,
) -> requests.Response | None:
    if not url:
        return None

    retries = _MAX_RETRIES if max_retries is None else max(0, max_retries)

    for attempt in range(retries + 1):
        blocked_for = _breaker.remaining_open_seconds() if wait_for_circuit else 0.0
        if blocked_for > 0:
            time.sleep(min(blocked_for, 10.0))

        _limiter.wait_turn()

        try:
            response = _session.get(
                url,
                headers=headers or DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=allow_redirects,
                stream=stream,
            )
        except Exception:
            _breaker.failure()
            if attempt >= retries:
                return None
            backoff = (_BACKOFF_BASE_SECONDS * (2**attempt)) + random.uniform(0.2, 1.2)
            time.sleep(backoff)
            continue

        if _looks_blocked(response):
            _breaker.failure()
            if attempt >= retries:
                return None
            backoff = (_BACKOFF_BASE_SECONDS * (2**attempt)) + random.uniform(0.5, 2.0)
            time.sleep(backoff)
            continue

        if response.status_code >= 500:
            _breaker.failure()
            if attempt >= retries:
                return None
            backoff = (_BACKOFF_BASE_SECONDS * (2**attempt)) + random.uniform(0.3, 1.5)
            time.sleep(backoff)
            continue

        _breaker.success()
        return response

    return None
