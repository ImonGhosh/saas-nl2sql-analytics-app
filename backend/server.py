import logging
import os

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
    handle_auth_callback,
    has_active_connection,
    init_mcp_db,
)

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


class McpAuthStartRequest(BaseModel):
    project_ref: str = Field(min_length=3)


class McpAuthStartResponse(BaseModel):
    auth_url: str


class McpAuthCallbackRequest(BaseModel):
    code: str = Field(min_length=4)
    state: str = Field(min_length=4)


class McpStatusResponse(BaseModel):
    connected: bool


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
