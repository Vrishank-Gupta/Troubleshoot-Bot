"""Simple cache: Redis when available, in-memory fallback for local dev."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# In-memory store: key -> (value, expiry_epoch_seconds)
_store: dict[str, tuple[Any, float]] = {}
_redis_client: Any = None


def _init_redis(redis_url: str) -> None:
    global _redis_client
    if not redis_url:
        return
    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(redis_url, decode_responses=True)
        logger.info("Redis cache connected: %s", redis_url)
    except ImportError:
        logger.warning("redis package not installed — using in-memory cache only")
    except Exception as e:
        logger.warning("Redis unavailable (%s) — using in-memory cache only", e)


async def get(key: str) -> Optional[Any]:
    # Try Redis first
    if _redis_client:
        try:
            raw = await _redis_client.get(key)
            if raw is not None:
                return json.loads(raw)
        except Exception as e:
            logger.debug("Redis get error: %s", e)

    # In-memory fallback
    entry = _store.get(key)
    if entry is None:
        return None
    value, expiry = entry
    if expiry and time.monotonic() > expiry:
        del _store[key]
        return None
    return value


async def set(key: str, value: Any, ttl: int = 300) -> None:
    serialised = json.dumps(value, default=str)

    if _redis_client:
        try:
            await _redis_client.setex(key, ttl, serialised)
        except Exception as e:
            logger.debug("Redis set error: %s", e)

    expiry = time.monotonic() + ttl if ttl else 0.0
    _store[key] = (json.loads(serialised), expiry)


async def delete(key: str) -> None:
    _store.pop(key, None)
    if _redis_client:
        try:
            await _redis_client.delete(key)
        except Exception as e:
            logger.debug("Redis delete error: %s", e)


async def invalidate_prefix(prefix: str) -> None:
    """Remove all in-memory keys starting with prefix."""
    to_delete = [k for k in list(_store) if k.startswith(prefix)]
    for k in to_delete:
        del _store[k]
    if _redis_client:
        try:
            keys = await _redis_client.keys(f"{prefix}*")
            if keys:
                await _redis_client.delete(*keys)
        except Exception as e:
            logger.debug("Redis invalidate error: %s", e)
