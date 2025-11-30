import json
import logging
import os
from typing import Any, Dict, Optional

import redis


logger = logging.getLogger("viewer_service.cache")


def _get_redis_client() -> Optional[redis.Redis]:
    """
    Create and return a Redis client using environment configuration.

    If Redis is not available, log a warning and return None so
    the service continues to work without caching.
    """
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))

    try:
        client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis not available for viewer_service (%r); cache disabled.", exc)
        return None


def get_cached_analysis(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Try to fetch a cached analysis for the given session_id from Redis.

    Returns:
        Parsed dict if present, or None if not cached / on error.
    """
    client = _get_redis_client()
    if client is None:
        return None

    key = f"viewer:analysis:{session_id}"
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read cached analysis for session_id=%s", session_id)
        return None


def set_cached_analysis(session_id: str, data: Dict[str, Any]) -> None:
    """
    Store an analysis dict in Redis for faster future reads.

    TTL (time-to-live) can be configured with VIEWER_CACHE_TTL env var
    (seconds). Defaults to 10 minutes.
    """
    client = _get_redis_client()
    if client is None:
        return

    ttl_seconds = int(os.getenv("VIEWER_CACHE_TTL", "600"))
    key = f"viewer:analysis:{session_id}"
    try:
        client.setex(key, ttl_seconds, json.dumps(data, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to cache analysis for session_id=%s", session_id)



