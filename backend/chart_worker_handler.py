import asyncio
import json
import logging
import os
from typing import Any, Dict

from secrets_manager import load_secrets

load_secrets()

from mcp_service import process_chart_job  # noqa: E402
from supabase_store import upsert_chart_job  # noqa: E402

logger = logging.getLogger("mcp")


async def _process_records(records: list[Dict[str, Any]]) -> None:
    max_receives = int(os.getenv("MCP_SQS_MAX_RECEIVE_COUNT", "3"))
    for record in records:
        body = record.get("body", "")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Job payload must be a JSON object.")
            job_id = str(payload.get("job_id") or "").strip()
            user_id = str(payload.get("user_id") or "").strip()
            question = str(payload.get("question") or "").strip()
            if not job_id or not user_id or not question:
                raise ValueError("Job payload missing job_id, user_id, or question.")

            receive_count = _receive_count(record)
            if receive_count >= max_receives:
                upsert_chart_job(
                    job_id,
                    user_id,
                    status="error",
                    error_message="Chart generation failed. Retry to continue.",
                )
                logger.warning(
                    "Chart job reached max receives. job_id=%s count=%s",
                    job_id,
                    receive_count,
                )
                continue

            await process_chart_job(job_id, user_id, question)
        except Exception:
            logger.exception("Chart job failed. body=%s", body)
            raise


def handler(event: Dict[str, Any], _context: Any) -> None:
    records = event.get("Records", []) if isinstance(event, dict) else []
    if not records:
        logger.info("No SQS records received.")
        return

    asyncio.run(_process_records(records))


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
