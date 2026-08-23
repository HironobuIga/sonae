"""Shared HTTP plumbing for Japanese government open-data endpoints.

All datasource modules go through `get_client()` so retries, timeouts,
user-agent, and on-disk caching behave consistently. Every endpoint we
touch is public, unauthenticated open data.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from sonae.config import settings

USER_AGENT = "sonae-agent/0.1 (+https://github.com/HironobuIga/sonae; disaster-readiness research)"

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
        )
    return _client


def _cache_path(url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    cache_dir = settings.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{digest}{suffix}"


def fetch_bytes(url: str, *, max_age_seconds: int | None = None, retries: int = 3) -> bytes:
    """GET a URL with retries; optionally serve from the on-disk cache.

    max_age_seconds=None disables caching (always fetch live).
    """
    path = _cache_path(url, ".bin")
    if max_age_seconds is not None and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < max_age_seconds:
            return path.read_bytes()

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = get_client().get(url)
            resp.raise_for_status()
            data = resp.content
            if max_age_seconds is not None:
                path.write_bytes(data)
            return data
        except (httpx.HTTPError, OSError) as exc:  # noqa: PERF203
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise ConnectionError(f"failed to fetch {url} after {retries} attempts: {last_error}")


def fetch_json(url: str, *, max_age_seconds: int | None = None) -> Any:
    return json.loads(fetch_bytes(url, max_age_seconds=max_age_seconds))
