import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from secrets_manager import load_secrets  # noqa: E402

load_secrets()

LOG_LEVEL = os.getenv("LOG_LEVEL")
if not LOG_LEVEL:
    LOG_LEVEL = (
        "INFO"
        if os.getenv("DEBUG_MCP_PAYLOADS", "").lower() in ("1", "true", "yes")
        else "WARNING"
    )
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from mcp_service import (  # noqa: E402
    create_authorization_url,
    disconnect_user,
    get_user_metadata,
    get_valid_tokens,
    handle_auth_callback,
    has_active_connection,
    submit_metadata_job,
)
from supabase_store import fetch_metadata_job, upsert_metadata_job  # noqa: E402
from redis_cache import (  # noqa: E402
    clear_cached_metadata,
    get_cached_metadata,
    set_cached_metadata,
)
from chart_agent import (  # noqa: E402
    ChartResponse,
    run_chart_query_agent,
    run_chart_spec_agent,
)
from chart_suggestions_agent import ChartSuggestions  # noqa: E402
from sql_agent import run_sql_agent  # noqa: E402

clerk_audience = os.getenv("CLERK_JWT_AUDIENCE") or None
clerk_issuer = os.getenv("CLERK_JWT_ISSUER") or None
clerk_leeway = float(os.getenv("CLERK_JWT_LEEWAY_SECONDS", "60"))
clerk_verify_iat = os.getenv("CLERK_VERIFY_IAT", "").lower() not in ("0", "false", "no")
clerk_config = ClerkConfig(
    jwks_url=os.getenv("CLERK_JWKS_URL"),
    audience=clerk_audience,
    issuer=clerk_issuer,
    verify_aud=bool(clerk_audience),
    verify_iss=bool(clerk_issuer),
    verify_iat=clerk_verify_iat,
    leeway=clerk_leeway,
)
clerk_guard = ClerkHTTPBearer(clerk_config)

app = FastAPI()
logger = logging.getLogger("mcp")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

USE_S3 = os.getenv("USE_S3", "false").lower() == "true"
S3_BUCKET = os.getenv("S3_BUCKET", "")
MEMORY_DIR = Path(os.getenv("MEMORY_DIR", str(Path(__file__).resolve().parent / "memory")))

if USE_S3:
    try:
        import boto3
        from botocore.exceptions import ClientError
    except Exception as exc:
        raise RuntimeError("USE_S3=true requires boto3 to be installed.") from exc
    s3_client = boto3.client("s3")


class McpAuthStartRequest(BaseModel):
    project_ref: str = Field(min_length=3)


class McpAuthStartResponse(BaseModel):
    auth_url: str


class McpAuthCallbackRequest(BaseModel):
    code: str = Field(min_length=4)
    state: str = Field(min_length=4)


class McpStatusResponse(BaseModel):
    connected: bool


class McpMetadataStatusResponse(BaseModel):
    status: str
    error_message: Optional[str] = None


class SqlQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: Optional[str] = None


class SqlQueryResponse(BaseModel):
    answer: str
    sql: str | None = None
    session_id: str


class ChartQueryRequest(BaseModel):
    question: str = Field(min_length=1)


class ChartLibraryRequest(BaseModel):
    summary: str
    chart_spec: Dict[str, Any]
    data: List[Dict[str, Any]]
    sql: str


class ChartLibraryItem(ChartLibraryRequest):
    saved_at: str


class ChartLibraryResponse(BaseModel):
    charts: List[ChartLibraryItem]

class ConversationSummary(BaseModel):
    session_id: str
    title: str
    message_count: int
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]


class ConversationDetailResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]



def _get_user_id(creds: HTTPAuthorizationCredentials) -> str:
    for attr in ("sub", "user_id"):
        value = getattr(creds, attr, None)
        if isinstance(value, str) and value:
            return value

    decoded = getattr(creds, "decoded", None)
    payload = getattr(creds, "payload", None)
    claims = getattr(creds, "claims", None)
    for container in (decoded, payload, claims):
        if isinstance(container, dict):
            user_id = container.get("sub") or container.get("user_id")
            if isinstance(user_id, str) and user_id:
                return user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unable to resolve user identity.",
    )


def _memory_key(user_id: str, session_id: str) -> str:
    safe_user = Path(user_id).name
    safe_session = Path(session_id).name
    if safe_session.endswith(".json"):
        filename = safe_session
    else:
        filename = f"{safe_session}.json"
    return f"{safe_user}/{filename}"


def _load_conversation(user_id: str, session_id: str) -> List[Dict[str, Any]]:
    key = _memory_key(user_id, session_id)
    if USE_S3:
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "NoSuchKey":
                return []
            raise
    file_path = MEMORY_DIR / key
    if file_path.exists():
        with file_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return []


def _save_conversation(user_id: str, session_id: str, messages: List[Dict[str, Any]]) -> None:
    key = _memory_key(user_id, session_id)
    if USE_S3:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(messages, indent=2),
            ContentType="application/json",
        )
        return
    file_path = MEMORY_DIR / key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(messages, handle, indent=2)


def _delete_conversation(user_id: str, session_id: str) -> None:
    key = _memory_key(user_id, session_id)
    if USE_S3:
        try:
            s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found.",
                ) from err
            raise
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
        return
    file_path = MEMORY_DIR / key
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    file_path.unlink()


def _delete_all_conversations(user_id: str) -> None:
    safe_user = Path(user_id).name
    if USE_S3:
        prefix = f"{safe_user}/"
        continuation_token = None
        while True:
            params = {"Bucket": S3_BUCKET, "Prefix": prefix}
            if continuation_token:
                params["ContinuationToken"] = continuation_token
            response = s3_client.list_objects_v2(**params)
            contents = response.get("Contents", [])
            if contents:
                keys = [{"Key": obj["Key"]} for obj in contents if obj.get("Key")]
                if keys:
                    s3_client.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": keys})
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
        return

    user_dir = MEMORY_DIR / safe_user
    if not user_dir.exists():
        return
    for file_path in user_dir.glob("*.json"):
        file_path.unlink(missing_ok=True)
    if not any(user_dir.iterdir()):
        user_dir.rmdir()


def _chart_memory_path(user_id: str) -> Path:
    safe_user = Path(user_id).name
    return MEMORY_DIR / "charts" / safe_user / "latest.json"


def _serialize_chart_response(response: ChartResponse) -> Dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return response.dict()


def _save_chart(user_id: str, response: ChartResponse) -> None:
    file_path = _chart_memory_path(user_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize_chart_response(response)
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _load_chart(user_id: str) -> Optional[ChartResponse]:
    file_path = _chart_memory_path(user_id)
    if not file_path.exists():
        return None
    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return ChartResponse(**payload)


def _delete_chart(user_id: str) -> None:
    file_path = _chart_memory_path(user_id)
    if file_path.exists():
        file_path.unlink()


def _chart_suggestions_key(user_id: str) -> str:
    safe_user = Path(user_id).name
    return f"charts/{safe_user}/suggestions.json"


def _chart_suggestions_path(user_id: str) -> Path:
    safe_user = Path(user_id).name
    return MEMORY_DIR / "charts" / safe_user / "suggestions.json"


def _load_suggestions(user_id: str) -> Optional[ChartSuggestions]:
    if USE_S3:
        key = _chart_suggestions_key(user_id)
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            payload = json.loads(response["Body"].read().decode("utf-8"))
            return ChartSuggestions(**payload)
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "NoSuchKey":
                return None
            raise
    file_path = _chart_suggestions_path(user_id)
    if not file_path.exists():
        return None
    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return ChartSuggestions(**payload)


def _delete_suggestions(user_id: str) -> None:
    if USE_S3:
        key = _chart_suggestions_key(user_id)
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
        return
    file_path = _chart_suggestions_path(user_id)
    if file_path.exists():
        file_path.unlink()

def _chart_library_key(user_id: str) -> str:
    safe_user = Path(user_id).name
    return f"charts/{safe_user}/library.json"


def _chart_library_path(user_id: str) -> Path:
    safe_user = Path(user_id).name
    return MEMORY_DIR / "charts" / safe_user / "library.json"


def _load_library(user_id: str) -> List[ChartLibraryItem]:
    if USE_S3:
        key = _chart_library_key(us_erid)
        try:
            response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
            payload = json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "NoSuchKey":
                return []
            raise
    else:
        file_path = _chart_library_path(user_id)
        if not file_path.exists():
            return []
        with file_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    charts = payload.get("charts", [])
    if not isinstance(charts, list):
        return []
    return [ChartLibraryItem(**item) for item in charts]


def _save_library(user_id: str, charts: List[ChartLibraryItem]) -> None:
    serialized = []
    for chart in charts:
        if hasattr(chart, "model_dump"):
            serialized.append(chart.model_dump())
        else:
            serialized.append(chart.dict())
    payload = {"charts": serialized}
    if USE_S3:
        key = _chart_library_key(user_id)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(payload, indent=2, default=str),
            ContentType="application/json",
        )
        return
    file_path = _chart_library_path(user_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _delete_library(user_id: str) -> None:
    if USE_S3:
        key = _chart_library_key(user_id)
        s3_client.delete_object(Bucket=S3_BUCKET, Key=key)
        return
    file_path = _chart_library_path(user_id)
    if file_path.exists():
        file_path.unlink()

def _conversation_title(messages: List[Dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                words = content.strip().split()
                return " ".join(words[:6])
    return "Conversation"


def _conversation_updated_at(
    messages: List[Dict[str, Any]], fallback_iso: str
) -> str:
    for message in reversed(messages):
        timestamp = message.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            return timestamp
    return fallback_iso


def _list_conversations(user_id: str) -> List[ConversationSummary]:
    safe_user = Path(user_id).name
    summaries: List[ConversationSummary] = []

    if USE_S3:
        prefix = f"{safe_user}/"
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        for obj in response.get("Contents", []):
            key = obj.get("Key")
            if not isinstance(key, str) or not key.endswith(".json"):
                continue
            session_id = Path(key).stem
            messages: List[Dict[str, Any]] = []
            try:
                s3_response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
                payload = json.loads(s3_response["Body"].read().decode("utf-8"))
                if isinstance(payload, list):
                    messages = payload
            except ClientError:
                messages = []
            fallback_dt = obj.get("LastModified")
            fallback_iso = (
                fallback_dt.isoformat() if fallback_dt else datetime.utcnow().isoformat()
            )
            summaries.append(
                ConversationSummary(
                    session_id=session_id,
                    title=_conversation_title(messages),
                    message_count=len(messages),
                    updated_at=_conversation_updated_at(messages, fallback_iso),
                )
            )
    else:
        user_dir = MEMORY_DIR / safe_user
        if user_dir.exists():
            for file_path in user_dir.glob("*.json"):
                session_id = file_path.stem
                messages: List[Dict[str, Any]] = []
                try:
                    with file_path.open("r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                    if isinstance(payload, list):
                        messages = payload
                except json.JSONDecodeError:
                    messages = []
                fallback_iso = datetime.utcfromtimestamp(
                    file_path.stat().st_mtime
                ).isoformat()
                summaries.append(
                    ConversationSummary(
                        session_id=session_id,
                        title=_conversation_title(messages),
                        message_count=len(messages),
                        updated_at=_conversation_updated_at(messages, fallback_iso),
                    )
                )

    summaries.sort(key=lambda item: item.updated_at, reverse=True)
    return summaries


logger.info("Backend startup complete. use_s3=%s", USE_S3)


@app.get("/api", response_class=PlainTextResponse)
async def api_endpoint(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    return "API Endpoint success"


@app.get("/health", response_class=PlainTextResponse)
async def health_check() -> str:
    return "ok"


@app.post("/mcp/auth/start", response_model=McpAuthStartResponse)
async def mcp_auth_start(
    payload: McpAuthStartRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> McpAuthStartResponse:
    user_id = _get_user_id(creds)
    logger.info("MCP auth start requested. user_id=%s project_ref=%s", user_id, payload.project_ref)
    try:
        auth_url = await create_authorization_url(user_id, payload.project_ref)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("MCP auth start failed")
        debug = os.getenv("DEBUG_MCP_ERRORS", "").lower() in ("1", "true", "yes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc) if debug else "Failed to start OAuth flow.",
        ) from exc
    return McpAuthStartResponse(auth_url=auth_url)


@app.post("/mcp/auth/callback", response_class=PlainTextResponse)
async def mcp_auth_callback(
    payload: McpAuthCallbackRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    logger.info("MCP auth callback received. user_id=%s state=%s", user_id, payload.state)
    try:
        await handle_auth_callback(user_id, payload.code, payload.state)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("MCP auth callback failed")
        debug = os.getenv("DEBUG_MCP_ERRORS", "").lower() in ("1", "true", "yes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc) if debug else "OAuth callback failed.",
        ) from exc
    logger.info("MCP auth callback completed. user_id=%s", user_id)
    return "Ready"


@app.get("/mcp/status", response_model=McpStatusResponse)
async def mcp_status(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> McpStatusResponse:
    user_id = _get_user_id(creds)
    connected = await has_active_connection(user_id)
    logger.debug("MCP status checked. user_id=%s connected=%s", user_id, connected)
    return McpStatusResponse(connected=connected)


@app.get("/mcp/metadata/status", response_model=McpMetadataStatusResponse)
async def mcp_metadata_status(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> McpMetadataStatusResponse:
    user_id = _get_user_id(creds)
    job = fetch_metadata_job(user_id)
    if not job:
        return McpMetadataStatusResponse(status="missing")
    status_value = job.get("status") or "missing"
    error_message = job.get("error_message")
    if status_value == "error":
        error_message = "Metadata extraction failed. Retry to continue."
    return McpMetadataStatusResponse(status=status_value, error_message=error_message)


@app.post("/mcp/metadata/retry", response_class=PlainTextResponse)
async def mcp_metadata_retry(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    job = fetch_metadata_job(user_id)
    if not job or job.get("status") != "error":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Metadata job is not in error state.",
        )
    project_ref = job.get("project_ref")
    if not isinstance(project_ref, str) or not project_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing project_ref for metadata job.",
        )
    upsert_metadata_job(
        user_id=user_id,
        project_ref=project_ref,
        status="queued",
        error_message=None,
    )
    await submit_metadata_job(user_id, project_ref)
    return "Queued"


@app.post("/mcp/disconnect", response_class=PlainTextResponse)
async def mcp_disconnect(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    logger.info("MCP disconnect requested. user_id=%s", user_id)
    await disconnect_user(user_id)
    await clear_cached_metadata(user_id)
    _delete_all_conversations(user_id)
    _delete_chart(user_id)
    _delete_suggestions(user_id)
    _delete_library(user_id)
    logger.info("MCP disconnect completed. user_id=%s", user_id)
    return "Disconnected"


@app.post("/sql/query", response_model=SqlQueryResponse)
async def sql_query(
    payload: SqlQueryRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> SqlQueryResponse:
    user_id = _get_user_id(creds)
    session_id = payload.session_id or uuid4().hex
    metadata_cache_key = "metadata"
    metadata = await get_cached_metadata(user_id, metadata_cache_key)
    print(f'SQL Query cached metadata: {metadata}\n')
    if not metadata:
        logger.info("Metadata cache miss for SQL query. user_id=%s", user_id)
        metadata = get_user_metadata(user_id)
        print(f'SQL Query Supabase metadata: {metadata}\n')
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No database metadata found for user. Connect Supabase first.",
            )
        await set_cached_metadata(user_id, metadata_cache_key, metadata)
    else:
        logger.debug("Metadata cache hit for SQL query. user_id=%s", user_id)
    try:
        tokens = await get_valid_tokens(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    conversation = _load_conversation(user_id, session_id)
    message_history = conversation[-10:]
    logger.info(
        "SQL query started. user_id=%s session_id=%s question_length=%s history_count=%s",
        user_id,
        session_id,
        len(payload.question),
        len(message_history),
    )

    trace_id = uuid4().hex
    trace_metadata = {
        "user_id": user_id,
        "session_id": session_id,
        "project_ref": tokens["project_ref"],
        "endpoint": "POST /sql/query",
    }
    try:
        result = await run_sql_agent(
            question=payload.question,
            metadata=metadata,
            access_token=tokens["access_token"],
            project_ref=tokens["project_ref"],
            message_history=message_history,
            trace_id=trace_id,
            trace_name="POST /sql/query",
            trace_user_id=user_id,
            trace_session_id=session_id,
            trace_metadata=trace_metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("SQL agent run failed")
        debug = os.getenv("DEBUG_MCP_ERRORS", "").lower() in ("1", "true", "yes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc) if debug else "SQL agent failed.",
        ) from exc

    answer = result.get("answer") or ""
    sql = result.get("sql")
    timestamp = datetime.utcnow().isoformat()
    conversation.append(
        {"role": "user", "content": payload.question, "timestamp": timestamp}
    )
    conversation.append(
        {
            "role": "assistant",
            "content": answer,
            "sql": sql,
            "timestamp": timestamp,
        }
    )
    _save_conversation(user_id, session_id, conversation)

    logger.info(
        "SQL query completed. user_id=%s session_id=%s has_sql=%s",
        user_id,
        session_id,
        bool(sql),
    )
    return SqlQueryResponse(answer=answer, sql=sql, session_id=session_id)


@app.get("/sql/conversations", response_model=ConversationListResponse)
async def sql_conversations(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ConversationListResponse:
    user_id = _get_user_id(creds)
    conversations = _list_conversations(user_id)
    logger.info(
        "Conversations listed. user_id=%s count=%s", user_id, len(conversations)
    )
    return ConversationListResponse(conversations=conversations)


@app.get("/sql/conversations/{session_id}", response_model=ConversationDetailResponse)
async def sql_conversation_detail(
    session_id: str,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ConversationDetailResponse:
    user_id = _get_user_id(creds)
    messages = _load_conversation(user_id, session_id)
    if not messages:
        key = _memory_key(user_id, session_id)
        if USE_S3:
            try:
                s3_client.head_object(Bucket=S3_BUCKET, Key=key)
            except ClientError as err:
                if err.response.get("Error", {}).get("Code") == "404":
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Conversation not found.",
                    ) from err
        else:
            file_path = MEMORY_DIR / key
            if not file_path.exists():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found.",
                )

    logger.info(
        "Conversation loaded. user_id=%s session_id=%s message_count=%s",
        user_id,
        session_id,
        len(messages),
    )
    return ConversationDetailResponse(session_id=session_id, messages=messages)


@app.delete("/sql/conversations/{session_id}", response_class=PlainTextResponse)
async def sql_conversation_delete(
    session_id: str,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    _delete_conversation(user_id, session_id)
    logger.info(
        "Conversation deleted. user_id=%s session_id=%s",
        user_id,
        session_id,
    )
    return "Deleted"


@app.post("/charts/query", response_model=ChartResponse)
async def charts_query(
    payload: ChartQueryRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ChartResponse:
    user_id = _get_user_id(creds)
    metadata_cache_key = "metadata"
    metadata = await get_cached_metadata(user_id, metadata_cache_key)
    print(f'Charts Cached metadata: {metadata}\n')
    if not metadata:
        logger.info("Metadata cache miss for chart query. user_id=%s", user_id)
        metadata = get_user_metadata(user_id)
        print(f'Charts Supabase metadata: {metadata}\n')
        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No database metadata found for user. Connect Supabase first.",
            )
        await set_cached_metadata(user_id, metadata_cache_key, metadata)
    else:
        logger.debug("Metadata cache hit for chart query. user_id=%s", user_id)
    try:
        tokens = await get_valid_tokens(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    trace_id = uuid4().hex
    trace_metadata = {
        "user_id": user_id,
        "session_id": None,
        "project_ref": tokens["project_ref"],
        "endpoint": "POST /charts/query",
    }
    try:
        query_result = await run_chart_query_agent(
            question=payload.question,
            metadata=metadata,
            access_token=tokens["access_token"],
            project_ref=tokens["project_ref"],
            trace_id=trace_id,
            trace_name="POST /charts/query",
            trace_user_id=user_id,
            trace_session_id=None,
            trace_metadata=trace_metadata,
        )
        response = await run_chart_spec_agent(
            question=payload.question,
            sql=query_result.sql,
            data=query_result.data,
            columns=query_result.columns,
            trace_id=trace_id,
            trace_name="POST /charts/query",
            trace_user_id=user_id,
            trace_session_id=None,
            trace_metadata=trace_metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Chart agent run failed")
        debug = os.getenv("DEBUG_MCP_ERRORS", "").lower() in ("1", "true", "yes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc) if debug else "Chart agent failed.",
        ) from exc

    logger.info(
        "Chart query completed. user_id=%s sql_length=%s rows=%s",
        user_id,
        len(query_result.sql) if query_result.sql else 0,
        len(query_result.data),
    )
    return response


@app.get("/charts/last", response_model=ChartResponse)
async def charts_last(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ChartResponse:
    user_id = _get_user_id(creds)
    chart = _load_chart(user_id)
    if not chart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved chart found.",
        )
    logger.info("Chart loaded. user_id=%s", user_id)
    return chart


@app.get("/charts/suggestions", response_model=ChartSuggestions)
async def charts_suggestions(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ChartSuggestions:
    user_id = _get_user_id(creds)
    suggestions = _load_suggestions(user_id)
    if not suggestions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chart suggestions found.",
        )
    logger.info("Chart suggestions loaded. user_id=%s", user_id)
    return suggestions


@app.get("/charts/library", response_model=ChartLibraryResponse)
async def charts_library(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ChartLibraryResponse:
    user_id = _get_user_id(creds)
    charts = _load_library(user_id)
    logger.info("Chart library loaded. user_id=%s count=%s", user_id, len(charts))
    return ChartLibraryResponse(charts=charts)


@app.post("/charts/library", response_model=ChartLibraryItem)
async def charts_library_save(
    payload: ChartLibraryRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ChartLibraryItem:
    user_id = _get_user_id(creds)
    charts = _load_library(user_id)
    if len(charts) >= 4:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chart library limit reached (max 4).",
        )
    saved_at = datetime.utcnow().isoformat()
    item = ChartLibraryItem(
        summary=payload.summary,
        chart_spec=payload.chart_spec,
        data=payload.data,
        sql=payload.sql,
        saved_at=saved_at,
    )
    charts.append(item)
    _save_library(user_id, charts)
    logger.info("Chart saved to library. user_id=%s saved_at=%s", user_id, saved_at)
    return item


@app.delete("/charts/library/{saved_at}", response_model=ChartLibraryResponse)
async def charts_library_delete(
    saved_at: str,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> ChartLibraryResponse:
    user_id = _get_user_id(creds)
    charts = _load_library(user_id)
    filtered = [chart for chart in charts if chart.saved_at != saved_at]
    if len(filtered) == len(charts):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chart not found in library.",
        )
    _save_library(user_id, filtered)
    logger.info("Chart removed from library. user_id=%s saved_at=%s", user_id, saved_at)
    return ChartLibraryResponse(charts=filtered)
