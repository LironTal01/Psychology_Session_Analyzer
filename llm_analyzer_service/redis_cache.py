import json
import logging
import os
from typing import Any, Dict, Optional

import redis


logger = logging.getLogger("llm_analyzer_service.redis_cache")


def _get_redis_client() -> Optional[redis.Redis]:
    """
    Create and return a Redis client using environment configuration.

    If Redis is not reachable or misconfigured, this function logs a warning
    and returns None so that callers can gracefully fall back to no caching.
    """
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))

    try:
        client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis not available (%r); caching will be disabled.", exc)
        return None


def get_analysis_from_cache(session_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a cached analysis for the given session_id from Redis.

    Returns:
        The analysis dictionary if found, or None if not present or on error.
    """
    client = _get_redis_client()
    if client is None:
        return None

    key = f"analysis:{session_id}"
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read cached analysis for session_id=%s", session_id)
        return None


def store_analysis_in_cache(session_id: str, analysis: Dict[str, Any]) -> None:
    """
    Store an analysis dictionary in Redis for quick future access.

    The TTL (time-to-live) can be controlled with the ANALYSIS_CACHE_TTL
    environment variable (in seconds). By default, entries live for 24 hours.
    """
    client = _get_redis_client()
    if client is None:
        return

    ttl_seconds = int(os.getenv("ANALYSIS_CACHE_TTL", "86400"))
    key = f"analysis:{session_id}"
    try:
        client.setex(key, ttl_seconds, json.dumps(analysis, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to cache analysis for session_id=%s", session_id)



