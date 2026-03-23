import logging
import os
from typing import Any, Dict, Optional

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")

_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
_TABLE = "mcp_metadata"
logger = logging.getLogger("mcp")


def upsert_metadata(user_id: str, project_ref: str, metadata: Dict[str, Any]) -> None:
    payload = {
        "user_id": user_id,
        "project_ref": project_ref,
        "metadata_json": metadata,
    }
    _supabase.table(_TABLE).upsert(payload).execute()
    logger.info("Supabase metadata upserted. user_id=%s project_ref=%s", user_id, project_ref)


def fetch_metadata(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = (
            _supabase.table(_TABLE)
            .select("metadata_json")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
    except Exception:
        logger.exception("Supabase metadata fetch failed. user_id=%s", user_id)
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
    _supabase.table(_TABLE).delete().eq("user_id", user_id).execute()
    logger.info("Supabase metadata deleted. user_id=%s", user_id)
