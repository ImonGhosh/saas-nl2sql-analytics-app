import base64
import hashlib
import json
import os
import secrets
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

MCP_DB_PATH = Path(
    os.getenv("MCP_DB_PATH", str(Path(__file__).resolve().parent / "mcp.sqlite3"))
)
MCP_BASE_URL = os.getenv("SUPABASE_MCP_BASE_URL", "https://mcp.supabase.com").rstrip("/")
MCP_SERVER_URL_TEMPLATE = os.getenv(
    "SUPABASE_MCP_SERVER_URL_TEMPLATE",
    "https://mcp.supabase.com/mcp?project_ref={project_ref}&read_only=true&features=database",
)
MCP_REDIRECT_URI = os.getenv(
    "SUPABASE_MCP_REDIRECT_URI", "http://localhost:3000/mcp/callback"
)
SUPABASE_OAUTH_AUTHORIZE_URL = os.getenv(
    "SUPABASE_OAUTH_AUTHORIZE_URL", "https://api.supabase.com/v1/oauth/authorize"
)
SUPABASE_OAUTH_TOKEN_URL = os.getenv(
    "SUPABASE_OAUTH_TOKEN_URL", "https://api.supabase.com/v1/oauth/token"
)
SUPABASE_OAUTH_ORG_SLUG = os.getenv("SUPABASE_OAUTH_ORGANIZATION_SLUG", "")
SUPABASE_OAUTH_CLIENT_AUTH_METHOD = os.getenv(
    "SUPABASE_OAUTH_CLIENT_AUTH_METHOD", "client_secret_basic"
).lower()

OAUTH_CLIENT_ID = os.getenv("SUPABASE_OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.getenv("SUPABASE_OAUTH_CLIENT_SECRET")
MCP_SCHEMAS = os.getenv("MCP_SCHEMAS", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _token_expired(expires_at: Optional[str], leeway_seconds: int = 60) -> bool:
    parsed = _parse_iso(expires_at)
    if not parsed:
        return bool(expires_at)
    return parsed <= (datetime.now(timezone.utc) + timedelta(seconds=leeway_seconds))


def _parse_expires_in(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _oauth_client_auth() -> Tuple[Dict[str, str], Dict[str, str]]:
    if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
        raise RuntimeError(
            "Missing SUPABASE_OAUTH_CLIENT_ID or SUPABASE_OAUTH_CLIENT_SECRET."
        )
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    payload: Dict[str, str] = {}
    if SUPABASE_OAUTH_CLIENT_AUTH_METHOD == "client_secret_post":
        payload["client_id"] = OAUTH_CLIENT_ID
        payload["client_secret"] = OAUTH_CLIENT_SECRET
        return headers, payload

    credentials = f"{OAUTH_CLIENT_ID}:{OAUTH_CLIENT_SECRET}"
    headers["Authorization"] = (
        "Basic " + base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    )
    return headers, payload


def _connect_db() -> sqlite3.Connection:
    MCP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(MCP_DB_PATH)
    conn.execute("pragma journal_mode = wal")
    return conn


def init_mcp_db() -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            create table if not exists oauth_clients (
                authorization_server text primary key,
                client_id text not null,
                client_secret text,
                token_endpoint_auth_method text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists mcp_auth_states (
                state text primary key,
                user_id text not null,
                project_ref text not null,
                code_verifier text not null,
                authorization_server text not null,
                created_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists mcp_tokens (
                user_id text primary key,
                project_ref text not null,
                access_token text not null,
                refresh_token text,
                token_type text,
                scope text,
                expires_at text,
                updated_at text not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists db_metadata (
                user_id text primary key,
                metadata_json text not null,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.commit()


def _get_oauth_client(authorization_server: str) -> Optional[Dict[str, Any]]:
    with _connect_db() as conn:
        row = conn.execute(
            """
            select client_id, client_secret, token_endpoint_auth_method
            from oauth_clients
            where authorization_server = ?
            """,
            (authorization_server,),
        ).fetchone()
        if not row:
            return None
        return {
            "client_id": row[0],
            "client_secret": row[1],
            "token_endpoint_auth_method": row[2],
        }


def _store_oauth_client(
    authorization_server: str, client_id: str, client_secret: Optional[str], auth_method: str
) -> None:
    now = _now_iso()
    with _connect_db() as conn:
        conn.execute(
            """
            insert into oauth_clients (
                authorization_server, client_id, client_secret, token_endpoint_auth_method,
                created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?)
            on conflict(authorization_server) do update set
                client_id = excluded.client_id,
                client_secret = excluded.client_secret,
                token_endpoint_auth_method = excluded.token_endpoint_auth_method,
                updated_at = excluded.updated_at
            """,
            (authorization_server, client_id, client_secret, auth_method, now, now),
        )
        conn.commit()


def _store_auth_state(
    state: str,
    user_id: str,
    project_ref: str,
    code_verifier: str,
    authorization_server: str,
) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            insert into mcp_auth_states (
                state, user_id, project_ref, code_verifier, authorization_server, created_at
            )
            values (?, ?, ?, ?, ?, ?)
            """,
            (state, user_id, project_ref, code_verifier, authorization_server, _now_iso()),
        )
        conn.commit()


def _load_auth_state(state: str) -> Optional[Dict[str, Any]]:
    with _connect_db() as conn:
        row = conn.execute(
            """
            select user_id, project_ref, code_verifier, authorization_server
            from mcp_auth_states
            where state = ?
            """,
            (state,),
        ).fetchone()
        if not row:
            return None
        return {
            "user_id": row[0],
            "project_ref": row[1],
            "code_verifier": row[2],
            "authorization_server": row[3],
        }


def _delete_auth_state(state: str) -> None:
    with _connect_db() as conn:
        conn.execute("delete from mcp_auth_states where state = ?", (state,))
        conn.commit()


def _store_tokens(
    user_id: str,
    project_ref: str,
    access_token: str,
    refresh_token: Optional[str],
    token_type: Optional[str],
    scope: Optional[str],
    expires_at: Optional[str],
) -> None:
    with _connect_db() as conn:
        conn.execute(
            """
            insert into mcp_tokens (
                user_id, project_ref, access_token, refresh_token, token_type, scope, expires_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(user_id) do update set
                project_ref = excluded.project_ref,
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                token_type = excluded.token_type,
                scope = excluded.scope,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                project_ref,
                access_token,
                refresh_token,
                token_type,
                scope,
                expires_at,
                _now_iso(),
            ),
        )
        conn.commit()


def _load_tokens(user_id: str) -> Optional[Dict[str, Any]]:
    with _connect_db() as conn:
        row = conn.execute(
            """
            select project_ref, access_token, refresh_token, token_type, scope, expires_at
            from mcp_tokens
            where user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "project_ref": row[0],
            "access_token": row[1],
            "refresh_token": row[2],
            "token_type": row[3],
            "scope": row[4],
            "expires_at": row[5],
        }


def _store_metadata(user_id: str, metadata: Dict[str, Any]) -> None:
    payload = json.dumps(metadata)
    now = _now_iso()
    with _connect_db() as conn:
        conn.execute(
            """
            insert into db_metadata (user_id, metadata_json, created_at, updated_at)
            values (?, ?, ?, ?)
            on conflict(user_id) do update set
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (user_id, payload, now, now),
        )
        conn.commit()


def _has_metadata(user_id: str) -> bool:
    with _connect_db() as conn:
        row = conn.execute(
            "select 1 from db_metadata where user_id = ? limit 1", (user_id,)
        ).fetchone()
        return row is not None


def get_user_metadata(user_id: str) -> Optional[Dict[str, Any]]:
    with _connect_db() as conn:
        row = conn.execute(
            "select metadata_json from db_metadata where user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return json.loads(row[0])


def get_user_tokens(user_id: str) -> Optional[Dict[str, Any]]:
    return _load_tokens(user_id)


async def get_valid_tokens(user_id: str) -> Dict[str, Any]:
    tokens = _load_tokens(user_id)
    if not tokens:
        raise RuntimeError("No MCP tokens found for user.")

    if _token_expired(tokens.get("expires_at")):
        refresh_token = tokens.get("refresh_token")
        try:
            token_data = await _refresh_access_token(refresh_token or "")
        except httpx.HTTPError as exc:
            raise RuntimeError(
                "Supabase connection expired. Please reconnect your MCP connection."
            ) from exc
        expires_in = _parse_expires_in(token_data.get("expires_in"))
        expires_at = tokens.get("expires_at")
        if expires_in is not None:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            ).isoformat()
        _store_tokens(
            user_id=user_id,
            project_ref=tokens["project_ref"],
            access_token=token_data.get("access_token") or tokens["access_token"],
            refresh_token=token_data.get("refresh_token") or refresh_token,
            token_type=token_data.get("token_type") or tokens.get("token_type"),
            scope=token_data.get("scope") or tokens.get("scope"),
            expires_at=expires_at,
        )
        tokens = _load_tokens(user_id) or tokens

    if not tokens.get("access_token"):
        raise RuntimeError("No access token available for MCP connection.")
    return tokens


def disconnect_user(user_id: str) -> None:
    with _connect_db() as conn:
        conn.execute("delete from mcp_tokens where user_id = ?", (user_id,))
        conn.execute("delete from db_metadata where user_id = ?", (user_id,))
        conn.execute("delete from mcp_auth_states where user_id = ?", (user_id,))
        conn.commit()


def has_active_connection(user_id: str) -> bool:
    return _has_metadata(user_id)


def build_mcp_url(project_ref: str) -> str:
    return _build_mcp_url(project_ref)


def _build_mcp_url(project_ref: str) -> str:
    template = MCP_SERVER_URL_TEMPLATE
    if "{project_ref}" in template:
        return template.format(project_ref=project_ref)
    separator = "&" if "?" in template else "?"
    return f"{template}{separator}project_ref={project_ref}"




def _parse_schema_filter() -> List[str]:
    if MCP_SCHEMAS.strip():
        raw = MCP_SCHEMAS
    else:
        raw = "public"
    schemas = [item.strip() for item in raw.split(",")]
    return [schema for schema in schemas if schema]


def _sql_in_list(values: List[str]) -> str:
    escaped = [value.replace("'", "''") for value in values]
    quoted = [f"'{value}'" for value in escaped]
    return ", ".join(quoted)


def _code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


async def create_authorization_url(user_id: str, project_ref: str) -> str:
    project_ref = project_ref.strip()
    if not project_ref:
        raise ValueError("project_ref is required.")
    if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
        raise RuntimeError(
            "Missing SUPABASE_OAUTH_CLIENT_ID or SUPABASE_OAUTH_CLIENT_SECRET."
        )

    state = secrets.token_urlsafe(32)
    verifier = _code_verifier()
    challenge = _code_challenge(verifier)

    _store_auth_state(state, user_id, project_ref, verifier, SUPABASE_OAUTH_AUTHORIZE_URL)

    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": MCP_REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if SUPABASE_OAUTH_ORG_SLUG:
        params["organization_slug"] = SUPABASE_OAUTH_ORG_SLUG
    return f"{SUPABASE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


async def handle_auth_callback(user_id: str, code: str, state: str) -> None:
    auth_state = _load_auth_state(state)
    if not auth_state or auth_state["user_id"] != user_id:
        raise ValueError("Invalid or expired OAuth state.")

    async with httpx.AsyncClient(timeout=20) as client:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": MCP_REDIRECT_URI,
            "code_verifier": auth_state["code_verifier"],
        }
        headers, auth_payload = _oauth_client_auth()
        payload.update(auth_payload)

        response = await client.post(SUPABASE_OAUTH_TOKEN_URL, data=payload, headers=headers)
        response.raise_for_status()
        token_data = response.json()

    expires_in = _parse_expires_in(token_data.get("expires_in"))
    expires_at = None
    if expires_in is not None:
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    _store_tokens(
        user_id=user_id,
        project_ref=auth_state["project_ref"],
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_type=token_data.get("token_type"),
        scope=token_data.get("scope"),
        expires_at=expires_at,
    )
    _delete_auth_state(state)

    metadata = await extract_metadata(user_id)
    _store_metadata(user_id, metadata)


async def _refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    if not refresh_token:
        raise RuntimeError("No refresh token available.")
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        headers, auth_payload = _oauth_client_auth()
        payload.update(auth_payload)
        response = await client.post(SUPABASE_OAUTH_TOKEN_URL, data=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def _first_json_in_text(text: str) -> Optional[Any]:
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch not in ("{", "["):
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
            return obj
        except json.JSONDecodeError:
            continue
    return None


def _parse_tool_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        messages = []
        for content in result.content:
            if isinstance(content, types.TextContent):
                messages.append(content.text)
        raise RuntimeError("Tool call failed: " + " | ".join(messages))

    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured

    for content in result.content:
        if isinstance(content, types.TextContent):
            data = _first_json_in_text(content.text)
            if data is not None:
                return data
    return {"raw": [c.text for c in result.content if isinstance(c, types.TextContent)]}


def _coerce_tabular_rows(rows: Any, columns: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(rows, list):
        return None

    col_names: List[str] = []
    if isinstance(columns, list):
        if columns and all(isinstance(col, dict) for col in columns):
            col_names = [str(col.get("name", "")) for col in columns if col.get("name")]
        elif columns and all(isinstance(col, str) for col in columns):
            col_names = [col for col in columns if col]

    if not col_names:
        return None

    normalized: List[Dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            normalized.append(row)
        elif isinstance(row, (list, tuple)):
            normalized.append(
                {
                    col_names[idx]: row[idx] if idx < len(row) else None
                    for idx in range(len(col_names))
                }
            )
    return normalized


def _normalize_rows(payload: Any, expected_keys: Optional[set[str]] = None) -> List[Dict[str, Any]]:
    candidates: List[List[Dict[str, Any]]] = []

    def add_candidate(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        if rows and not all(isinstance(item, dict) for item in rows):
            return
        if rows:
            candidates.append(rows)

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            if "rows" in obj and ("columns" in obj or "fields" in obj):
                coerced = _coerce_tabular_rows(obj.get("rows"), obj.get("columns") or obj.get("fields"))
                if coerced:
                    candidates.append(coerced)
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            add_candidate(obj)
            for value in obj:
                visit(value)
        elif isinstance(obj, str):
            extracted = _first_json_in_text(obj)
            if extracted is not None:
                visit(extracted)

    visit(payload)

    if not candidates:
        return []

    expected_keys_lc = {key.lower() for key in expected_keys} if expected_keys else None

    def score(rows: List[Dict[str, Any]]) -> Tuple[int, int]:
        if not expected_keys_lc or not rows:
            return (0, len(rows))
        match_count = 0
        for row in rows[:3]:
            if not isinstance(row, dict):
                continue
            row_keys = {str(key).lower() for key in row.keys()}
            match_count += len(row_keys & expected_keys_lc)
        return (match_count, len(rows))

    best_rows = max(candidates, key=score)
    if not expected_keys_lc:
        return best_rows

    normalized_rows: List[Dict[str, Any]] = []
    for row in best_rows:
        if isinstance(row, dict):
            normalized_rows.append({str(key).lower(): value for key, value in row.items()})
    return normalized_rows


def _resolve_sql_key(input_schema: Dict[str, Any]) -> str:
    props = (input_schema or {}).get("properties", {}) or {}
    for key in ("sql", "query", "statement"):
        if key in props:
            return key
    required = (input_schema or {}).get("required", []) or []
    if len(required) == 1:
        return required[0]
    raise ValueError("Unable to infer SQL argument name for execute_sql tool.")


async def _execute_sql(
    session: ClientSession, sql: str, expected_keys: Optional[set[str]] = None
) -> List[Dict[str, Any]]:
    tools = await session.list_tools()
    tool_map = {tool.name: tool for tool in tools.tools}
    if "execute_sql" not in tool_map:
        raise RuntimeError("execute_sql tool is not available.")
    input_schema = tool_map["execute_sql"].inputSchema or {}
    sql_key = _resolve_sql_key(input_schema)
    result = await session.call_tool("execute_sql", arguments={sql_key: sql})
    payload = _parse_tool_result(result)
    return _normalize_rows(payload, expected_keys=expected_keys)


def _build_metadata(
    tables: List[Dict[str, Any]],
    columns: List[Dict[str, Any]],
    constraints: List[Dict[str, Any]],
    table_comments: List[Dict[str, Any]],
    column_comments: List[Dict[str, Any]],
    mcp_url: str,
    project_ref: str,
) -> Dict[str, Any]:
    table_comment_map = {
        (row["table_schema"], row["table_name"]): row.get("table_comment")
        for row in table_comments
        if row.get("table_schema") and row.get("table_name")
    }
    column_comment_map = {
        (row["table_schema"], row["table_name"], row["column_name"]): row.get("column_comment")
        for row in column_comments
        if row.get("table_schema") and row.get("table_name") and row.get("column_name")
    }

    schema_map: Dict[str, Dict[str, Any]] = {}
    table_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for row in tables:
        schema = row.get("table_schema")
        table = row.get("table_name")
        if not schema or not table:
            continue
        schema_entry = schema_map.setdefault(schema, {"schema": schema, "tables": []})
        table_entry = {
            "name": table,
            "comment": table_comment_map.get((schema, table)),
            "columns": [],
            "primary_key": [],
            "unique_constraints": [],
            "foreign_keys": [],
        }
        schema_entry["tables"].append(table_entry)
        table_map[(schema, table)] = table_entry

    for row in columns:
        schema = row.get("table_schema")
        table = row.get("table_name")
        if not schema or not table:
            continue
        table_entry = table_map.setdefault(
            (schema, table),
            {
                "name": table,
                "comment": table_comment_map.get((schema, table)),
                "columns": [],
                "primary_key": [],
                "unique_constraints": [],
                "foreign_keys": [],
            },
        )
        if schema not in schema_map:
            schema_map[schema] = {"schema": schema, "tables": [table_entry]}

        table_entry["columns"].append(
            {
                "name": row.get("column_name"),
                "data_type": row.get("data_type"),
                "is_nullable": (row.get("is_nullable") == "YES"),
                "default": row.get("column_default"),
                "ordinal_position": row.get("ordinal_position"),
                "comment": column_comment_map.get((schema, table, row.get("column_name"))),
            }
        )

    constraint_groups: Dict[Tuple[str, str, str, str], Dict[str, Any]] = defaultdict(
        lambda: {"columns": [], "ref_schema": None, "ref_table": None, "ref_columns": []}
    )

    for row in constraints:
        schema = row.get("table_schema")
        table = row.get("table_name")
        name = row.get("constraint_name")
        ctype = row.get("constraint_type")
        if not schema or not table or not name or not ctype:
            continue
        key = (schema, table, name, ctype)
        group = constraint_groups[key]
        if row.get("column_name"):
            group["columns"].append((row.get("ordinal_position") or 0, row.get("column_name")))
        if ctype == "FOREIGN KEY":
            group["ref_schema"] = row.get("foreign_table_schema")
            group["ref_table"] = row.get("foreign_table_name")
            if row.get("foreign_column_name"):
                group["ref_columns"].append(
                    (row.get("ordinal_position") or 0, row.get("foreign_column_name"))
                )

    relationships: List[Dict[str, Any]] = []
    for (schema, table, name, ctype), group in constraint_groups.items():
        columns = [col for _, col in sorted(group["columns"], key=lambda x: x[0])]
        table_entry = table_map.get((schema, table))
        if not table_entry:
            continue
        if ctype == "PRIMARY KEY":
            table_entry["primary_key"] = columns
        elif ctype == "UNIQUE":
            table_entry["unique_constraints"].append({"name": name, "columns": columns})
        elif ctype == "FOREIGN KEY":
            ref_columns = [col for _, col in sorted(group["ref_columns"], key=lambda x: x[0])]
            fk = {
                "name": name,
                "columns": columns,
                "references": {
                    "schema": group["ref_schema"],
                    "table": group["ref_table"],
                    "columns": ref_columns,
                },
            }
            table_entry["foreign_keys"].append(fk)
            relationships.append(
                {
                    "from": {"schema": schema, "table": table, "columns": columns},
                    "to": {
                        "schema": group["ref_schema"],
                        "table": group["ref_table"],
                        "columns": ref_columns,
                    },
                    "constraint": name,
                }
            )

    return {
        "version": "v1",
        "generated_at": _now_iso(),
        "source": {
            "mcp_server_url": mcp_url,
            "project_ref": project_ref,
        },
        "schemas": list(schema_map.values()),
        "relationships": relationships,
    }


async def extract_metadata(user_id: str) -> Dict[str, Any]:
    token_info = _load_tokens(user_id)
    if not token_info:
        raise RuntimeError("No MCP tokens found for user.")

    project_ref = token_info["project_ref"]
    access_token = token_info["access_token"]
    mcp_url = _build_mcp_url(project_ref)
    headers = {"Authorization": f"Bearer {access_token}"}
    allowed_schemas = _parse_schema_filter()
    schema_filter = f"and table_schema in ({_sql_in_list(allowed_schemas)})"
    tc_schema_filter = f"and tc.table_schema in ({_sql_in_list(allowed_schemas)})"
    ns_filter = f"and n.nspname in ({_sql_in_list(allowed_schemas)})"

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as http_client:
        async with streamable_http_client(mcp_url, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                tables_sql = """
                    select table_schema, table_name
                    from information_schema.tables
                    where table_type = 'BASE TABLE'
                      and table_schema not in ('pg_catalog', 'information_schema')
                      {schema_filter}
                    order by table_schema, table_name;
                """.format(schema_filter=schema_filter)
                columns_sql = """
                    select table_schema, table_name, column_name, data_type, is_nullable, column_default, ordinal_position
                    from information_schema.columns
                    where table_schema not in ('pg_catalog', 'information_schema')
                      {schema_filter}
                    order by table_schema, table_name, ordinal_position;
                """.format(schema_filter=schema_filter)
                constraints_sql = """
                    select
                        tc.table_schema,
                        tc.table_name,
                        tc.constraint_name,
                        tc.constraint_type,
                        kcu.column_name,
                        kcu.ordinal_position,
                        ccu.table_schema as foreign_table_schema,
                        ccu.table_name as foreign_table_name,
                        ccu.column_name as foreign_column_name
                    from information_schema.table_constraints tc
                    left join information_schema.key_column_usage kcu
                        on tc.constraint_name = kcu.constraint_name
                        and tc.table_schema = kcu.table_schema
                    left join information_schema.constraint_column_usage ccu
                        on tc.constraint_name = ccu.constraint_name
                        and tc.table_schema = ccu.table_schema
                    where tc.table_schema not in ('pg_catalog', 'information_schema')
                      {schema_filter};
                """.format(schema_filter=tc_schema_filter)
                fallback_fk_sql = """
                    select
                        n.nspname as table_schema,
                        cl.relname as table_name,
                        con.conname as constraint_name,
                        'FOREIGN KEY' as constraint_type,
                        a.attname as column_name,
                        conkey.ord as ordinal_position,
                        nf.nspname as foreign_table_schema,
                        clf.relname as foreign_table_name,
                        af.attname as foreign_column_name
                    from pg_catalog.pg_constraint con
                    join pg_catalog.pg_class cl on cl.oid = con.conrelid
                    join pg_catalog.pg_namespace n on n.oid = cl.relnamespace
                    join pg_catalog.pg_class clf on clf.oid = con.confrelid
                    join pg_catalog.pg_namespace nf on nf.oid = clf.relnamespace
                    join unnest(con.conkey) with ordinality as conkey(attnum, ord) on true
                    join pg_catalog.pg_attribute a
                        on a.attrelid = con.conrelid and a.attnum = conkey.attnum
                    join unnest(con.confkey) with ordinality as confkey(attnum, ord)
                        on confkey.ord = conkey.ord
                    join pg_catalog.pg_attribute af
                        on af.attrelid = con.confrelid and af.attnum = confkey.attnum
                    where con.contype = 'f'
                      and n.nspname not in ('pg_catalog', 'information_schema')
                      {ns_filter};
                """.format(ns_filter=ns_filter)
                table_comments_sql = """
                    select n.nspname as table_schema, c.relname as table_name, d.description as table_comment
                    from pg_catalog.pg_class c
                    join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                    left join pg_catalog.pg_description d on d.objoid = c.oid and d.objsubid = 0
                    where c.relkind = 'r'
                      and n.nspname not in ('pg_catalog', 'information_schema')
                      {ns_filter};
                """.format(ns_filter=ns_filter)
                column_comments_sql = """
                    select
                        n.nspname as table_schema,
                        c.relname as table_name,
                        a.attname as column_name,
                        d.description as column_comment
                    from pg_catalog.pg_class c
                    join pg_catalog.pg_namespace n on n.oid = c.relnamespace
                    join pg_catalog.pg_attribute a
                        on a.attrelid = c.oid
                        and a.attnum > 0
                        and not a.attisdropped
                    left join pg_catalog.pg_description d
                        on d.objoid = c.oid and d.objsubid = a.attnum
                    where c.relkind = 'r'
                      and n.nspname not in ('pg_catalog', 'information_schema')
                      {ns_filter};
                """.format(ns_filter=ns_filter)

                tables_rows = await _execute_sql(
                    session, tables_sql, expected_keys={"table_schema", "table_name"}
                )
                columns_rows = await _execute_sql(
                    session,
                    columns_sql,
                    expected_keys={"table_schema", "table_name", "column_name"},
                )
                constraints_rows = await _execute_sql(
                    session,
                    constraints_sql,
                    expected_keys={
                        "table_schema",
                        "table_name",
                        "constraint_name",
                        "constraint_type",
                        "column_name",
                    },
                )
                has_fk = any(
                    (row.get("constraint_type") or "").upper() == "FOREIGN KEY"
                    for row in constraints_rows
                )
                if not has_fk:
                    fallback_rows = await _execute_sql(
                        session,
                        fallback_fk_sql,
                        expected_keys={
                            "table_schema",
                            "table_name",
                            "constraint_name",
                            "constraint_type",
                            "column_name",
                            "foreign_table_schema",
                            "foreign_table_name",
                            "foreign_column_name",
                        },
                    )
                    if fallback_rows:
                        constraints_rows.extend(fallback_rows)
                table_comments_rows = await _execute_sql(
                    session,
                    table_comments_sql,
                    expected_keys={"table_schema", "table_name", "table_comment"},
                )
                column_comments_rows = await _execute_sql(
                    session,
                    column_comments_sql,
                    expected_keys={"table_schema", "table_name", "column_name", "column_comment"},
                )

                return _build_metadata(
                    tables_rows,
                    columns_rows,
                    constraints_rows,
                    table_comments_rows,
                    column_comments_rows,
                    mcp_url,
                    project_ref,
                )
