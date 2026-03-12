import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse, urlunparse

from dotenv import load_dotenv

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi_clerk_auth import (
    ClerkConfig,
    ClerkHTTPBearer,
    HTTPAuthorizationCredentials,
)
from pydantic import BaseModel, Field

from cryptography.fernet import Fernet, InvalidToken
import psycopg

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = Path(
    os.getenv(
        "CONNECTIONS_DB_PATH",
        str(Path(__file__).resolve().parent / "connections.sqlite3"),
    )
)

FERNET_KEY = os.getenv("CONNECTION_ENCRYPTION_KEY")
if not FERNET_KEY:
    raise RuntimeError(
        "CONNECTION_ENCRYPTION_KEY is required to encrypt connection strings."
    )
fernet = Fernet(FERNET_KEY)


class DbConnectRequest(BaseModel):
    connection_string: str = Field(min_length=10)


class DbStatusResponse(BaseModel):
    connected: bool


def _init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("pragma journal_mode = wal")
        conn.execute(
            """
            create table if not exists connections (
                user_id text primary key,
                encrypted_payload text not null,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.commit()


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


def _ensure_ssl_required(connection_string: str) -> str:
    parsed = urlparse(connection_string)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid connection string scheme.",
        )

    params = parse_qs(parsed.query)
    sslmode = params.get("sslmode", [None])[0]
    if sslmode is None:
        params["sslmode"] = ["require"]
        query = "&".join(
            f"{key}={value}"
            for key, values in params.items()
            for value in values
        )
        return urlunparse(parsed._replace(query=query))
    if sslmode != "require":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sslmode=require is required.",
        )
    return connection_string


def _validate_db_connection(connection_string: str) -> None:
    with psycopg.connect(connection_string, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("select 1;")
            cur.fetchone()


def _store_connection(user_id: str, connection_string: str) -> None:
    try:
        encrypted = fernet.encrypt(connection_string.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encrypt connection string.",
        ) from exc

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("pragma journal_mode = wal")
        conn.execute(
            """
            insert into connections (user_id, encrypted_payload, created_at, updated_at)
            values (?, ?, ?, ?)
            on conflict(user_id) do update set
                encrypted_payload = excluded.encrypted_payload,
                updated_at = excluded.updated_at
            """,
            (user_id, encrypted, now, now),
        )
        conn.commit()


_init_db()


def _has_connection(user_id: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "select 1 from connections where user_id = ? limit 1", (user_id,)
        ).fetchone()
        return row is not None


def _delete_connection(user_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("delete from connections where user_id = ?", (user_id,))
        conn.commit()


@app.get("/api", response_class=PlainTextResponse)
async def api_endpoint(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    return "API Endpoint success"


@app.post("/db/connect", response_class=PlainTextResponse)
async def connect_db(
    payload: DbConnectRequest,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    connection_string = payload.connection_string.strip()
    if not connection_string:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection string is required.",
        )

    connection_string = _ensure_ssl_required(connection_string)

    try:
        await asyncio.to_thread(_validate_db_connection, connection_string)
    except Exception as exc:
        debug = os.getenv("DEBUG_CONNECTION_ERRORS", "").lower() in ("1", "true", "yes")
        detail = (
            f"Connection failed: {exc}"
            if debug
            else "Connection failed. Please verify your credentials."
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from exc

    _store_connection(user_id, connection_string)
    return "Connection Successful"


@app.get("/db/status", response_model=DbStatusResponse)
async def db_status(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> DbStatusResponse:
    user_id = _get_user_id(creds)
    return DbStatusResponse(connected=_has_connection(user_id))


@app.post("/db/disconnect", response_class=PlainTextResponse)
async def disconnect_db(
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
) -> str:
    user_id = _get_user_id(creds)
    _delete_connection(user_id)
    return "Disconnected"
