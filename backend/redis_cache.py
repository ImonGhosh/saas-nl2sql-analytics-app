import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional
from weakref import WeakKeyDictionary

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
METADATA_CACHE_TTL_SECONDS = int(os.getenv("METADATA_CACHE_TTL_SECONDS", "3600"))
TOKENS_CACHE_TTL_SECONDS = int(os.getenv("MCP_TOKENS_CACHE_TTL_SECONDS", "900"))
AUTH_STATE_CACHE_TTL_SECONDS = int(os.getenv("MCP_AUTH_STATE_CACHE_TTL_SECONDS", "900"))

_clients: "WeakKeyDictionary[asyncio.AbstractEventLoop, redis.Redis]" = WeakKeyDictionary()
logger = logging.getLogger("mcp")


def _metadata_key(user_id: str, session_id: str) -> str:
    return f"mcp:metadata:{user_id}:{session_id}"

#This is useful because later, if you want to clear all cached metadata for a user, you need to know which session keys exist.
def _sessions_key(user_id: str) -> str:
    return f"mcp:metadata_sessions:{user_id}"


def _tokens_key(user_id: str) -> str:
    return f"mcp:tokens:{user_id}"


def _auth_state_key(user_id: str, state: str) -> str:
    return f"mcp:auth_state:{user_id}:{state}"


def _auth_states_key(user_id: str) -> str:
    return f"mcp:auth_states:{user_id}"


def _get_client() -> redis.Redis:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return redis.from_url(REDIS_URL, decode_responses=True)
    client = _clients.get(loop)
    if client is None:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        _clients[loop] = client
    return client


async def get_cached_metadata(user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    client = _get_client()
    raw = await client.get(_metadata_key(user_id, session_id))
    if not raw:
        logger.debug("Redis metadata cache miss. user_id=%s session_id=%s", user_id, session_id)
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Redis metadata cache decode failed. user_id=%s session_id=%s", user_id, session_id)
        return None
    logger.debug("Redis metadata cache hit. user_id=%s session_id=%s", user_id, session_id)
    return payload if isinstance(payload, dict) else None


async def set_cached_metadata(user_id: str, session_id: str, metadata: Dict[str, Any]) -> None:
    client = _get_client()
    await client.set(
        _metadata_key(user_id, session_id),
        json.dumps(metadata),
        ex=METADATA_CACHE_TTL_SECONDS,
    )
    sessions_key = _sessions_key(user_id)
    await client.sadd(sessions_key, session_id) #stores all session ids for a user
    await client.expire(sessions_key, METADATA_CACHE_TTL_SECONDS)
    logger.info("Redis metadata cached. user_id=%s session_id=%s", user_id, session_id)


async def clear_cached_metadata(user_id: str) -> None:
    client = _get_client()
    sessions_key = _sessions_key(user_id)
    sessions = await client.smembers(sessions_key)
    if sessions:
        keys = [_metadata_key(user_id, session_id) for session_id in sessions]
        await client.delete(*keys)
    await client.delete(sessions_key)
    logger.info("Redis metadata cache cleared. user_id=%s sessions=%s", user_id, len(sessions or []))


async def get_cached_tokens(user_id: str) -> Optional[Dict[str, Any]]:
    client = _get_client()
    raw = await client.get(_tokens_key(user_id))
    if not raw:
        logger.debug("Redis tokens cache miss. user_id=%s", user_id)
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Redis tokens cache decode failed. user_id=%s", user_id)
        return None
    logger.debug("Redis tokens cache hit. user_id=%s", user_id)
    return payload if isinstance(payload, dict) else None


async def set_cached_tokens(user_id: str, tokens: Dict[str, Any], ttl_seconds: int | None = None) -> None:
    ttl = ttl_seconds or TOKENS_CACHE_TTL_SECONDS
    client = _get_client()
    await client.set(_tokens_key(user_id), json.dumps(tokens), ex=ttl)
    logger.info("Redis tokens cached. user_id=%s ttl=%s", user_id, ttl)


async def clear_cached_tokens(user_id: str) -> None:
    client = _get_client()
    await client.delete(_tokens_key(user_id))
    logger.info("Redis tokens cache cleared. user_id=%s", user_id)


async def get_cached_auth_state(user_id: str, state: str) -> Optional[Dict[str, Any]]:
    client = _get_client()
    raw = await client.get(_auth_state_key(user_id, state))
    if not raw:
        logger.debug("Redis auth state cache miss. user_id=%s state=%s", user_id, state)
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Redis auth state cache decode failed. user_id=%s state=%s", user_id, state)
        return None
    logger.debug("Redis auth state cache hit. user_id=%s state=%s", user_id, state)
    return payload if isinstance(payload, dict) else None


async def set_cached_auth_state(
    user_id: str, state: str, payload: Dict[str, Any], ttl_seconds: int | None = None
) -> None:
    ttl = ttl_seconds or AUTH_STATE_CACHE_TTL_SECONDS
    client = _get_client()
    await client.set(_auth_state_key(user_id, state), json.dumps(payload), ex=ttl)
    states_key = _auth_states_key(user_id)
    await client.sadd(states_key, state)
    await client.expire(states_key, ttl)
    logger.info("Redis auth state cached. user_id=%s state=%s ttl=%s", user_id, state, ttl)


async def delete_cached_auth_state(user_id: str, state: str) -> None:
    client = _get_client()
    await client.delete(_auth_state_key(user_id, state))
    await client.srem(_auth_states_key(user_id), state)
    logger.info("Redis auth state cache cleared. user_id=%s state=%s", user_id, state)


async def clear_cached_auth_states(user_id: str) -> None:
    client = _get_client()
    states_key = _auth_states_key(user_id)
    states = await client.smembers(states_key)
    if states:
        keys = [_auth_state_key(user_id, state) for state in states]
        await client.delete(*keys)
    await client.delete(states_key)
    logger.info("Redis auth state cache cleared. user_id=%s states=%s", user_id, len(states or []))
