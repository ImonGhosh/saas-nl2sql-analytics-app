import asyncio
import json
import logging
from typing import Any, Dict

from secrets_manager import load_secrets

load_secrets()

from mcp_service import process_metadata_job  # noqa: E402

logger = logging.getLogger("mcp")


async def _process_records(records: list[Dict[str, Any]]) -> None:
    for record in records:
        body = record.get("body", "")
        try:
            payload = _parse_body(body)
            user_id = str(payload.get("user_id") or "").strip()
            project_ref = str(payload.get("project_ref") or "").strip()
            if not user_id or not project_ref:
                raise ValueError("Job payload missing user_id or project_ref.")

            await process_metadata_job(user_id, project_ref)
        except Exception:
            logger.exception("Metadata job failed. body=%s", body)
            raise


def _parse_body(body: str) -> Dict[str, Any]:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("Job payload must be a JSON object.")
    return payload


def handler(event: Dict[str, Any], _context: Any) -> None:
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not records:
        logger.info("No SQS records received.")
        return

    asyncio.run(_process_records(records))
