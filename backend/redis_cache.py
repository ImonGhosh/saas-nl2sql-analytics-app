import json
import os
from typing import Any, Dict, Optional

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
METADATA_CACHE_TTL_SECONDS = int(os.getenv("METADATA_CACHE_TTL_SECONDS", "3600"))

_client = redis.from_url(REDIS_URL, decode_responses=True)


def _metadata_key(user_id: str, session_id: str) -> str:
    return f"mcp:metadata:{user_id}:{session_id}"

#This is useful because later, if you want to clear all cached metadata for a user, you need to know which session keys exist.
def _sessions_key(user_id: str) -> str:
    return f"mcp:metadata_sessions:{user_id}"


async def get_cached_metadata(user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    raw = await _client.get(_metadata_key(user_id, session_id))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def set_cached_metadata(user_id: str, session_id: str, metadata: Dict[str, Any]) -> None:
    await _client.set(
        _metadata_key(user_id, session_id),
        json.dumps(metadata),
        ex=METADATA_CACHE_TTL_SECONDS,
    )
    sessions_key = _sessions_key(user_id)
    await _client.sadd(sessions_key, session_id) #stores all session ids for a user
    await _client.expire(sessions_key, METADATA_CACHE_TTL_SECONDS)


async def clear_cached_metadata(user_id: str) -> None:
    sessions_key = _sessions_key(user_id)
    sessions = await _client.smembers(sessions_key)
    if sessions:
        keys = [_metadata_key(user_id, session_id) for session_id in sessions]
        await _client.delete(*keys)
    await _client.delete(sessions_key)
