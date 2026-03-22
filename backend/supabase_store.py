import os
from typing import Any, Dict, Optional

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")

_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
_TABLE = "mcp_metadata"


def upsert_metadata(user_id: str, project_ref: str, metadata: Dict[str, Any]) -> None:
    payload = {
        "user_id": user_id,
        "project_ref": project_ref,
        "metadata_json": metadata,
    }
    _supabase.table(_TABLE).upsert(payload).execute()


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
        return None
    data = getattr(response, "data", None)
    if not isinstance(data, dict):
        return None
    metadata = data.get("metadata_json")
    if isinstance(metadata, dict):
        return metadata
    return None


def delete_metadata(user_id: str) -> None:
    _supabase.table(_TABLE).delete().eq("user_id", user_id).execute()
