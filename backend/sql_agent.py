import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.mcp import MCPServerStreamableHTTP

from langfuse_tracing import end_span, extract_prompt_tokens, start_span, start_trace
from llm_provider import build_openai_model
from mcp_service import build_mcp_url

logger = logging.getLogger("mcp")

@dataclass
class SqlAgentDeps:
    metadata: Dict[str, Any]
    mcp_url: str


_AGENT: Agent | None = None


def _compact_metadata(
    metadata: Dict[str, Any],
    *,
    include_types: bool = True,
    include_constraints: bool = True,
    include_relationships: bool = True,
    columns_only: bool = False,
    max_columns: Optional[int] = None,
    max_tables: Optional[int] = None,
) -> Dict[str, Any]:
    schemas_out: list[Dict[str, Any]] = []
    for schema in metadata.get("schemas", []) or []:
        schema_name = schema.get("schema")
        if not schema_name:
            continue
        tables = schema.get("tables", []) or []
        if max_tables is not None and len(tables) > max_tables:
            tables = tables[:max_tables]
            schema_truncated = True
        else:
            schema_truncated = False

        table_out: list[Dict[str, Any]] = []
        for table in tables:
            table_name = table.get("name")
            if not table_name:
                continue
            cols = table.get("columns", []) or []
            if max_columns is not None and len(cols) > max_columns:
                cols = cols[:max_columns]
                cols_truncated = True
            else:
                cols_truncated = False

            if columns_only:
                col_payload = [c.get("name") for c in cols if c.get("name")]
            else:
                col_payload = []
                for col in cols:
                    col_name = col.get("name")
                    if not col_name:
                        continue
                    entry = {"name": col_name}
                    if include_types:
                        entry["data_type"] = col.get("data_type")
                    col_payload.append(entry)

            table_entry: Dict[str, Any] = {"name": table_name, "columns": col_payload}
            if cols_truncated:
                table_entry["columns_truncated"] = True
            if include_constraints:
                if table.get("primary_key"):
                    table_entry["primary_key"] = table.get("primary_key")
                if table.get("unique_constraints"):
                    table_entry["unique_constraints"] = table.get("unique_constraints")
                if table.get("foreign_keys"):
                    table_entry["foreign_keys"] = table.get("foreign_keys")
            table_out.append(table_entry)

        schema_entry: Dict[str, Any] = {"schema": schema_name, "tables": table_out}
        if schema_truncated:
            schema_entry["tables_truncated"] = True
        schemas_out.append(schema_entry)

    payload: Dict[str, Any] = {"schemas": schemas_out}
    if include_relationships:
        relationships = metadata.get("relationships") or []
        if relationships:
            payload["relationships"] = relationships
    return payload


def _metadata_table_list(metadata: Dict[str, Any], max_chars: int) -> str:
    lines: list[str] = []
    for schema in metadata.get("schemas", []) or []:
        schema_name = schema.get("schema")
        if not schema_name:
            continue
        table_names = [t.get("name") for t in schema.get("tables", []) or [] if t.get("name")]
        line = f"{schema_name}: " + ", ".join(table_names)
        if lines:
            candidate = "\n".join(lines + [line])
        else:
            candidate = line
        if len(candidate) > max_chars:
            break
        lines.append(line)
    if not lines:
        return "{}"
    return "\n".join(lines)


def _format_metadata_for_prompt(metadata: Dict[str, Any]) -> str:
    max_chars = int(os.getenv("METADATA_MAX_CHARS", "200000"))
    max_columns = int(os.getenv("METADATA_MAX_COLUMNS", "60"))
    max_tables = int(os.getenv("METADATA_MAX_TABLES", "200"))

    variants = [
        lambda: _compact_metadata(metadata, include_types=True, include_constraints=True, include_relationships=True),
        lambda: _compact_metadata(metadata, include_types=True, include_constraints=True, include_relationships=False),
        lambda: _compact_metadata(metadata, include_types=True, include_constraints=False, include_relationships=False),
        lambda: _compact_metadata(metadata, include_types=False, include_constraints=False, include_relationships=False),
        lambda: _compact_metadata(
            metadata,
            include_types=False,
            include_constraints=False,
            include_relationships=False,
            max_columns=max_columns,
        ),
        lambda: _compact_metadata(
            metadata,
            include_types=False,
            include_constraints=False,
            include_relationships=False,
            columns_only=True,
            max_columns=max_columns,
        ),
        lambda: _compact_metadata(
            metadata,
            include_types=False,
            include_constraints=False,
            include_relationships=False,
            columns_only=True,
            max_columns=max_columns,
            max_tables=max_tables,
        ),
    ]

    for build in variants:
        payload = build()
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        if len(text) <= max_chars:
            return text

    return _metadata_table_list(metadata, max_chars)


def _get_model_name() -> str:
    model = os.getenv("SQL_AGENT_MODEL")
    if not model:
        raise RuntimeError("SQL_AGENT_MODEL is not set.")
    return model


def _get_agent() -> Agent:
    global _AGENT
    if _AGENT is not None:
        return _AGENT

    model_name = _get_model_name()
    model = build_openai_model(model_name)
    _AGENT = Agent(
        model,
        deps_type=SqlAgentDeps,
        instructions=(
            "You are a SQL assistant for a Supabase Postgres database. "
            "Use ONLY the provided database metadata to infer tables, columns, and relationships. "
            "Follow below steps while responding :"
            "If the user question can be answered by only looking at the metadata, do not create any SQL query or use any tools. Simply answer based on the metadata"
            "Else, query the database to answer the user question, generate a single, read-only SQL query (no INSERT/UPDATE/DELETE/DDL)."
            "Always prefer fully qualified table names when the schema is known. "
            "If the request is ambiguous, make a reasonable assumption and proceed. "
            "Use LIMIT when returning example rows (default to LIMIT 20 if not specified). "
            "Call the execute_sql tool to run the query, then respond with a concise plain-text summary of the results."
        ),
        output_type=str,
    )

    @_AGENT.instructions
    def add_metadata(ctx: RunContext[SqlAgentDeps]) -> str:
        metadata_json = _format_metadata_for_prompt(ctx.deps.metadata)
        return f"Database metadata:\n{metadata_json}"

    return _AGENT


def _extract_sql_from_args(tool_args: Dict[str, Any]) -> Optional[str]:
    for key in ("sql", "query", "statement"):
        value = tool_args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if len(tool_args) == 1:
        only_value = next(iter(tool_args.values()))
        if isinstance(only_value, str) and only_value.strip():
            return only_value.strip()
    return None


def _build_message_history(
    messages: Optional[list[Dict[str, Any]]],
) -> list[object]:
    if not messages:
        return []
    history: list[object] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        if role == "user":
            history.append(ModelRequest.user_text_prompt(content))
        elif role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content)]))
    return history


async def run_sql_agent(
    *,
    question: str,
    metadata: Dict[str, Any],
    access_token: str,
    project_ref: str,
    message_history: Optional[list[Dict[str, Any]]] = None,
    trace_id: Optional[str] = None,
    trace_name: Optional[str] = None,
    trace_user_id: Optional[str] = None,
    trace_session_id: Optional[str] = None,
    trace_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[str]]:
    if not question or not question.strip():
        raise ValueError("Question is required.")

    mcp_url = build_mcp_url(project_ref)
    deps = SqlAgentDeps(metadata=metadata, mcp_url=mcp_url)

    last_sql: Optional[str] = None
    logger.info(
        "SQL agent run started. user_id=%s session_id=%s question_length=%s",
        trace_user_id,
        trace_session_id,
        len(question),
    )

    async def capture_tool_call(
        ctx: RunContext[SqlAgentDeps],
        call_tool: Any,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> Any:
        nonlocal last_sql
        if tool_name == "execute_sql":
            extracted = _extract_sql_from_args(tool_args)
            if extracted:
                last_sql = extracted
        return await call_tool(tool_name, tool_args, None)

    server = MCPServerStreamableHTTP(
        mcp_url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
        process_tool_call=capture_tool_call,
    )
    agent = _get_agent()
    history = _build_message_history(message_history)
    trace = start_trace(
        trace_id=trace_id,
        name=trace_name,
        user_id=trace_user_id,
        session_id=trace_session_id,
        metadata=trace_metadata,
    )
    span_metadata: Dict[str, Any] = {"model": _get_model_name()}
    span = start_span(trace, name="sql_agent.run", metadata=span_metadata, input=question)
    start_ms = time.perf_counter()
    try:
        async with agent:
            result = await agent.run(
                question.strip(),
                deps=deps,
                toolsets=[server],
                message_history=history,
            )
        prompt_tokens = extract_prompt_tokens(result)
        if prompt_tokens is not None:
            span_metadata["prompt_tokens"] = prompt_tokens
        span_metadata["latency_ms"] = round((time.perf_counter() - start_ms) * 1000, 2)
        span_metadata["success"] = True
        if last_sql:
            span_metadata["sql"] = last_sql
        end_span(span, metadata=span_metadata)
    except Exception as exc:
        logger.exception(
            "SQL agent run failed. user_id=%s session_id=%s",
            trace_user_id,
            trace_session_id,
        )
        span_metadata["latency_ms"] = round((time.perf_counter() - start_ms) * 1000, 2)
        span_metadata["success"] = False
        span_metadata["error"] = str(exc)
        if last_sql:
            span_metadata["sql"] = last_sql
        end_span(span, metadata=span_metadata, error=str(exc))
        raise

    logger.info(
        "SQL agent run completed. user_id=%s session_id=%s has_sql=%s",
        trace_user_id,
        trace_session_id,
        bool(last_sql),
    )
    return {"answer": str(result.output), "sql": last_sql}
