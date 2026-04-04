import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")

_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
_METADATA_TABLE = "mcp_metadata"
_TOKENS_TABLE = "mcp_tokens"
_AUTH_STATES_TABLE = "mcp_auth_states"
_METADATA_JOBS_TABLE = "mcp_metadata_jobs"
_CHART_JOBS_TABLE = "mcp_chart_jobs"
logger = logging.getLogger("mcp")


def upsert_metadata(user_id: str, project_ref: str, metadata: Dict[str, Any]) -> None:
    payload = {
        "user_id": user_id,
        "project_ref": project_ref,
        "metadata_json": metadata,
    }
    _supabase.table(_METADATA_TABLE).upsert(payload).execute()
    logger.info("Supabase metadata upserted. user_id=%s project_ref=%s", user_id, project_ref)


def fetch_metadata(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_METADATA_TABLE)
            .select("metadata_json")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        logger.exception("Supabase metadata fetch failed. user_id=%s", user_id)
        return None
    if response is None:
        logger.debug("Supabase metadata missing. user_id=%s", user_id)
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        logger.debug("Supabase metadata missing. user_id=%s", user_id)
        return None
    metadata = data.get("metadata_json")
    if isinstance(metadata, dict):
        logger.info("Supabase metadata fetched. user_id=%s", user_id)
        return metadata
    return None


def delete_metadata(user_id: str) -> None:
    _supabase.table(_METADATA_TABLE).delete().eq("user_id", user_id).execute()
    logger.info("Supabase metadata deleted. user_id=%s", user_id)


def upsert_tokens(
    user_id: str,
    project_ref: str,
    access_token: str,
    refresh_token: Optional[str],
    token_type: Optional[str],
    scope: Optional[str],
    expires_at: Optional[str],
    updated_at: str,
) -> None:
    payload = {
        "user_id": user_id,
        "project_ref": project_ref,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_type,
        "scope": scope,
        "expires_at": expires_at,
        "updated_at": updated_at,
    }
    _supabase.table(_TOKENS_TABLE).upsert(payload).execute()
    logger.info("Supabase tokens upserted. user_id=%s", user_id)


def fetch_tokens(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_TOKENS_TABLE)
            .select(
                "project_ref, access_token, refresh_token, token_type, scope, expires_at, updated_at"
            )
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        logger.exception("Supabase tokens fetch failed. user_id=%s", user_id)
        return None
    if response is None:
        logger.debug("Supabase tokens missing. user_id=%s", user_id)
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        logger.debug("Supabase tokens missing. user_id=%s", user_id)
        return None
    logger.info("Supabase tokens fetched. user_id=%s", user_id)
    return data


def delete_tokens(user_id: str) -> None:
    _supabase.table(_TOKENS_TABLE).delete().eq("user_id", user_id).execute()
    logger.info("Supabase tokens deleted. user_id=%s", user_id)


def insert_auth_state(
    state: str,
    user_id: str,
    project_ref: str,
    code_verifier: str,
    authorization_server: str,
    created_at: str,
) -> None:
    payload = {
        "state": state,
        "user_id": user_id,
        "project_ref": project_ref,
        "code_verifier": code_verifier,
        "authorization_server": authorization_server,
        "created_at": created_at,
    }
    _supabase.table(_AUTH_STATES_TABLE).insert(payload).execute()
    logger.info("Supabase auth state inserted. user_id=%s state=%s", user_id, state)


def fetch_auth_state(state: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_AUTH_STATES_TABLE)
            .select("state, user_id, project_ref, code_verifier, authorization_server, created_at")
            .eq("state", state)
            .maybe_single()
            .execute()
        )
    except Exception:
        logger.exception("Supabase auth state fetch failed. state=%s", state)
        return None
    if response is None:
        logger.debug("Supabase auth state missing. state=%s", state)
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        logger.debug("Supabase auth state missing. state=%s", state)
        return None
    logger.info("Supabase auth state fetched. state=%s", state)
    return data


def delete_auth_state(state: str) -> None:
    _supabase.table(_AUTH_STATES_TABLE).delete().eq("state", state).execute()
    logger.info("Supabase auth state deleted. state=%s", state)


def delete_auth_states_for_user(user_id: str) -> None:
    _supabase.table(_AUTH_STATES_TABLE).delete().eq("user_id", user_id).execute()
    logger.info("Supabase auth states deleted. user_id=%s", user_id)


def upsert_metadata_job(
    user_id: str,
    project_ref: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    payload = {
        "user_id": user_id,
        "project_ref": project_ref,
        "status": status,
        "error_message": error_message,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _supabase.table(_METADATA_JOBS_TABLE).upsert(payload).execute()
    logger.info("Supabase metadata job upserted. user_id=%s status=%s", user_id, status)


def fetch_metadata_job(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_METADATA_JOBS_TABLE)
            .select("user_id, project_ref, status, error_message, updated_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        logger.exception("Supabase metadata job fetch failed. user_id=%s", user_id)
        return None
    if response is None:
        logger.debug("Supabase metadata job missing. user_id=%s", user_id)
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        logger.debug("Supabase metadata job missing. user_id=%s", user_id)
        return None
    logger.info("Supabase metadata job fetched. user_id=%s", user_id)
    return data


def delete_metadata_job(user_id: str) -> None:
    _supabase.table(_METADATA_JOBS_TABLE).delete().eq("user_id", user_id).execute()
    logger.info("Supabase metadata job deleted. user_id=%s", user_id)


def upsert_chart_job(
    job_id: str,
    user_id: str,
    status: str,
    question: Optional[str] = None,
    question_hash: Optional[str] = None,
    result_json: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    payload: Dict[str, Any] = {
        "id": job_id,
        "user_id": user_id,
        "status": status,
        "error_message": error_message,
        "updated_at": datetime.utcnow().isoformat(),
    }
    if question is not None:
        payload["question"] = question
    if question_hash is not None:
        payload["question_hash"] = question_hash
    if result_json is not None:
        payload["result_json"] = result_json
    _supabase.table(_CHART_JOBS_TABLE).upsert(payload).execute()
    logger.info("Supabase chart job upserted. job_id=%s status=%s", job_id, status)


def fetch_chart_job(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_CHART_JOBS_TABLE)
            .select(
                "id, user_id, status, question, question_hash, result_json, error_message, created_at, updated_at"
            )
            .eq("id", job_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        logger.exception("Supabase chart job fetch failed. job_id=%s", job_id)
        return None
    if response is None:
        logger.debug("Supabase chart job missing. job_id=%s", job_id)
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        logger.debug("Supabase chart job missing. job_id=%s", job_id)
        return None
    logger.info("Supabase chart job fetched. job_id=%s", job_id)
    return data


def fetch_active_chart_job_for_question(
    user_id: str, question_hash: str
) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_CHART_JOBS_TABLE)
            .select("id, user_id, status, question, question_hash, updated_at")
            .eq("user_id", user_id)
            .eq("question_hash", question_hash)
            .in_("status", ["queued", "running"])
            .order("updated_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
    except Exception:
        logger.exception(
            "Supabase chart job lookup failed. user_id=%s question_hash=%s",
            user_id,
            question_hash,
        )
        return None
    if response is None:
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        return None
    return data
