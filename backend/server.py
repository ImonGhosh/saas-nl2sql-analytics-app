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
    get_user_tokens,
    handle_auth_callback,
    has_active_connection,
    init_mcp_db,
)
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
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
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


class SqlQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: Optional[str] = None


class SqlQueryResponse(BaseModel):
    answer: str
    sql: str | None = None
    session_id: str


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


init_mcp_db()


@app.get("/api", response_class=PlainTextResponse)
async def api_endpoint(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    return "API Endpoint success"


@app.post("/mcp/auth/start", response_model=McpAuthStartResponse)
async def mcp_auth_start(
    payload: McpAuthStartRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> McpAuthStartResponse:
    user_id = _get_user_id(creds)
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
    return "Ready"


@app.get("/mcp/status", response_model=McpStatusResponse)
async def mcp_status(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> McpStatusResponse:
    user_id = _get_user_id(creds)
    return McpStatusResponse(connected=has_active_connection(user_id))


@app.post("/mcp/disconnect", response_class=PlainTextResponse)
async def mcp_disconnect(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    disconnect_user(user_id)
    return "Disconnected"


@app.post("/sql/query", response_model=SqlQueryResponse)
async def sql_query(
    payload: SqlQueryRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> SqlQueryResponse:
    user_id = _get_user_id(creds)
    session_id = payload.session_id or uuid4().hex
    metadata = get_user_metadata(user_id)
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No database metadata found for user. Connect Supabase first.",
        )
    tokens = get_user_tokens(user_id)
    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active Supabase connection found for user.",
        )

    conversation = _load_conversation(user_id, session_id)
    message_history = conversation[-10:]

    try:
        result = await run_sql_agent(
            question=payload.question,
            metadata=metadata,
            access_token=tokens["access_token"],
            project_ref=tokens["project_ref"],
            message_history=message_history,
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

    return SqlQueryResponse(answer=answer, sql=sql, session_id=session_id)
