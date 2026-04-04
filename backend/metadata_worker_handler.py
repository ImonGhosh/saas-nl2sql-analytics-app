import asyncio
import json
import logging
import os
from typing import Any, Dict

from secrets_manager import load_secrets

load_secrets()

from mcp_service import process_metadata_job  # noqa: E402
from supabase_store import upsert_metadata_job  # noqa: E402

logger = logging.getLogger("mcp")


async def _process_records(records: list[Dict[str, Any]]) -> None:
    max_receives = int(os.getenv("MCP_SQS_MAX_RECEIVE_COUNT", "3"))
    for record in records:
        body = record.get("body", "")
        try:
            payload = _parse_body(body)
            user_id = str(payload.get("user_id") or "").strip()
            project_ref = str(payload.get("project_ref") or "").strip()
            if not user_id or not project_ref:
                raise ValueError("Job payload missing user_id or project_ref.")

            receive_count = _receive_count(record)
            if receive_count >= max_receives:
                upsert_metadata_job(
                    user_id,
                    project_ref,
                    status="error",
                    error_message="Metadata extraction failed. Retry to continue.",
                )
                logger.warning(
                    "Metadata job reached max receives. user_id=%s count=%s",
                    user_id,
                    receive_count,
                )
                continue

            await process_metadata_job(user_id, project_ref)
        except Exception:
            logger.exception("Metadata job failed. body=%s", body)
            raise


def _parse_body(body: str) -> Dict[str, Any]:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Job payload must be a JSON object.")
    return payload


def _receive_count(record: Dict[str, Any]) -> int:
    attributes = record.get("attributes") if isinstance(record, dict) else None
    if not isinstance(attributes, dict):
        return 1
    raw = attributes.get("ApproximateReceiveCount")
    try:
        count = int(raw)
        return count if count > 0 else 1
    except (TypeError, ValueError):
        return 1


def handler(event: Dict[str, Any], _context: Any) -> None:
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not records:
        logger.info("No SQS records received.")
        return

    asyncio.run(_process_records(records))
