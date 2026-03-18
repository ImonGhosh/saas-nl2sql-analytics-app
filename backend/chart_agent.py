import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mcp import types
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.mcp import MCPServerStreamableHTTP

from mcp_service import build_mcp_url


class ChartQueryResult(BaseModel):
    sql: str = Field(..., description="The SQL query executed to fetch chart data.")
    data: List[Dict[str, Any]] = Field(
        default_factory=list, description="Normalized rows returned from the query."
    )
    columns: Optional[List[str]] = Field(
        default=None, description="Ordered column names when available."
    )


class ChartSpecOutput(BaseModel):
    summary: str = Field(..., description="Short, data-grounded summary.")
    chart_spec: Dict[str, Any] = Field(
        ..., description="Vega-Lite spec referencing a named data set called 'values'."
    )


class ChartResponse(BaseModel):
    summary: str
    chart_spec: Dict[str, Any]
    data: List[Dict[str, Any]]
    sql: str


@dataclass
class ChartQueryDeps:
    metadata: Dict[str, Any]
    mcp_url: str


@dataclass
class ChartSpecDeps:
    question: str
    sql: str
    data: List[Dict[str, Any]]
    columns: Optional[List[str]]


_QUERY_AGENT: Agent | None = None
_SPEC_AGENT: Agent | None = None


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
    schemas_out: List[Dict[str, Any]] = []
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

        table_out: List[Dict[str, Any]] = []
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
    lines: List[str] = []
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


def _get_chart_query_model() -> str:
    model = os.getenv("CHART_QUERY_MODEL") or os.getenv("SQL_AGENT_MODEL")
    if not model:
        raise RuntimeError("CHART_QUERY_MODEL (or SQL_AGENT_MODEL) is not set.")
    return model


def _get_chart_spec_model() -> str:
    model = os.getenv("CHART_SPEC_MODEL") or os.getenv("SQL_AGENT_MODEL")
    if not model:
        raise RuntimeError("CHART_SPEC_MODEL (or SQL_AGENT_MODEL) is not set.")
    return model


def _get_query_agent() -> Agent:
    global _QUERY_AGENT
    if _QUERY_AGENT is not None:
        return _QUERY_AGENT

    _QUERY_AGENT = Agent(
        _get_chart_query_model(),
        deps_type=ChartQueryDeps,
        instructions=(
            "You are a chart data agent for a Supabase Postgres database. "
            "Use ONLY the provided database metadata to infer tables, columns, and relationships. "
            "Always generate a single, read-only SQL query (no INSERT/UPDATE/DELETE/DDL). "
            "Always call the execute_sql tool once to fetch data before responding. "
            "Prefer aggregated or summarized results suitable for charting, with sensible LIMITs (max 200 rows). "
            "Return the SQL you executed in the output."
        ),
        output_type=ChartQueryResult,
    )

    @_QUERY_AGENT.instructions
    def add_metadata(ctx: RunContext[ChartQueryDeps]) -> str:
        metadata_json = _format_metadata_for_prompt(ctx.deps.metadata)
        return f"Database metadata:\n{metadata_json}"

    return _QUERY_AGENT


def _get_spec_agent() -> Agent:
    global _SPEC_AGENT
    if _SPEC_AGENT is not None:
        return _SPEC_AGENT

    _SPEC_AGENT = Agent(
        _get_chart_spec_model(),
        deps_type=ChartSpecDeps,
        instructions=(
            "You are a chart spec agent. Create a Vega-Lite spec from the provided data. "
            "Strictly return JSON only in the structured output. "
            "The spec must reference data by name using: data: { name: \"values\" }. "
            "Include a useful title and choose an appropriate mark and encodings. "
            "Use temporal types for date/time, quantitative for numbers, nominal for categories. "
            "Do not invent fields that are not present in the data. "
            "Example of vega-lite spec (line chart): "
            "{"
            "\"$schema\":\"https://vega.github.io/schema/vega-lite/v5.json\","
            "\"title\":\"Monthly Revenue\","
            "\"data\":{\"name\":\"values\"},"
            "\"mark\":{\"type\":\"line\",\"point\":true},"
            "\"encoding\":{"
            "\"x\":{\"field\":\"month\",\"type\":\"temporal\",\"title\":\"Month\"},"
            "\"y\":{\"field\":\"revenue\",\"type\":\"quantitative\",\"title\":\"Revenue\"}"
            "}"
            "} "
            "Example of vega-lite spec (bar chart): "
            "{"
            "\"$schema\":\"https://vega.github.io/schema/vega-lite/v5.json\","
            "\"title\":\"Revenue by Plan\","
            "\"data\":{\"name\":\"values\"},"
            "\"mark\":{\"type\":\"bar\"},"
            "\"encoding\":{"
            "\"x\":{\"field\":\"plan\",\"type\":\"nominal\",\"title\":\"Plan\"},"
            "\"y\":{\"field\":\"revenue\",\"type\":\"quantitative\",\"title\":\"Revenue\"}"
            "}"
            "}"
        ),
        output_type=ChartSpecOutput,
    )

    @_SPEC_AGENT.instructions
    def add_query_context(ctx: RunContext[ChartSpecDeps]) -> str:
        sample_limit = int(os.getenv("CHART_SPEC_SAMPLE_ROWS", "200"))
        sample_rows = ctx.deps.data[:sample_limit]
        payload = {
            "question": ctx.deps.question,
            "sql": ctx.deps.sql,
            "columns": ctx.deps.columns,
            "rows": sample_rows,
        }
        return "Query results (JSON, possibly truncated):\n" + json.dumps(
            payload, indent=2, default=str
        )

    return _SPEC_AGENT


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
    if isinstance(result, dict):
        if result.get("isError"):
            raise RuntimeError("Tool call failed: " + str(result))
        if "structuredContent" in result and result["structuredContent"] is not None:
            return result["structuredContent"]
        if "content" in result:
            content = result["content"]
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        data = _first_json_in_text(item.get("text", ""))
                        if data is not None:
                            return data
            return {"raw": content}
        return result

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


def _normalize_rows(payload: Any) -> List[Dict[str, Any]]:
    candidates: List[List[Dict[str, Any]]] = []

    def add_candidate(rows: Any) -> None:
        if not isinstance(rows, list):
            return
        if rows and not all(isinstance(item, dict) for item in rows):
            return
        if rows is not None:
            candidates.append(rows)

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            if "rows" in obj and ("columns" in obj or "fields" in obj):
                coerced = _coerce_tabular_rows(obj.get("rows"), obj.get("columns") or obj.get("fields"))
                if coerced is not None:
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

    def score(rows: List[Dict[str, Any]]) -> int:
        return len(rows)

    best_rows = max(candidates, key=score)
    return best_rows


def _extract_columns(payload: Any, rows: List[Dict[str, Any]]) -> Optional[List[str]]:
    if isinstance(payload, dict):
        columns = payload.get("columns") or payload.get("fields")
        if isinstance(columns, list):
            if columns and all(isinstance(col, dict) for col in columns):
                names = [str(col.get("name", "")) for col in columns if col.get("name")]
                if names:
                    return names
            if columns and all(isinstance(col, str) for col in columns):
                return [col for col in columns if col]
    if rows:
        return list(rows[0].keys())
    return None


async def run_chart_query_agent(
    *,
    question: str,
    metadata: Dict[str, Any],
    access_token: str,
    project_ref: str,
    message_history: Optional[list[Dict[str, Any]]] = None,
) -> ChartQueryResult:
    if not question or not question.strip():
        raise ValueError("Question is required.")

    mcp_url = build_mcp_url(project_ref)
    deps = ChartQueryDeps(metadata=metadata, mcp_url=mcp_url)

    last_sql: Optional[str] = None
    last_rows: Optional[List[Dict[str, Any]]] = None
    last_columns: Optional[List[str]] = None

    async def capture_tool_call(
        ctx: RunContext[ChartQueryDeps],
        call_tool: Any,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> Any:
        nonlocal last_sql, last_rows, last_columns
        result = await call_tool(tool_name, tool_args, None)
        if tool_name == "execute_sql":
            extracted = _extract_sql_from_args(tool_args)
            if extracted:
                last_sql = extracted
            payload = _parse_tool_result(result)
            rows = _normalize_rows(payload)
            last_rows = rows
            last_columns = _extract_columns(payload, rows)
        return result

    server = MCPServerStreamableHTTP(
        mcp_url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
        process_tool_call=capture_tool_call,
    )
    agent = _get_query_agent()
    history = _build_message_history(message_history)
    async with agent:
        await agent.run(
            question.strip(),
            deps=deps,
            toolsets=[server],
            message_history=history,
        )

    if not last_sql:
        raise RuntimeError("Chart query agent did not execute SQL.")
    if last_rows is None:
        raise RuntimeError("Chart query agent returned no rows.")

    return ChartQueryResult(sql=last_sql, data=last_rows, columns=last_columns)


async def run_chart_spec_agent(
    *,
    question: str,
    sql: str,
    data: List[Dict[str, Any]],
    columns: Optional[List[str]] = None,
) -> ChartResponse:
    deps = ChartSpecDeps(question=question, sql=sql, data=data, columns=columns)
    agent = _get_spec_agent()
    async with agent:
        result = await agent.run(
            "Create the chart spec and summary based on the provided query results.",
            deps=deps,
        )

    output = result.output
    return ChartResponse(
        summary=output.summary,
        chart_spec=output.chart_spec,
        data=data,
        sql=sql,
    )
