"""Redis client (caching, simple counters)."""

from __future__ import annotations

import redis

from ckg.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def ping() -> bool:
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
