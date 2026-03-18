import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.mcp import MCPServerStreamableHTTP

from mcp_service import build_mcp_url


@dataclass
class SqlAgentDeps:
    metadata: Dict[str, Any]
    mcp_url: str


_AGENT: Agent | None = None


def _get_model_name() -> str:
    model = os.getenv("SQL_AGENT_MODEL")
    if not model:
        raise RuntimeError("SQL_AGENT_MODEL is not set.")
    return model


def _get_agent() -> Agent:
    global _AGENT
    if _AGENT is not None:
        return _AGENT

    _AGENT = Agent(
        _get_model_name(),
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
        metadata_json = json.dumps(ctx.deps.metadata, indent=2, sort_keys=True)
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
) -> Dict[str, Optional[str]]:
    if not question or not question.strip():
        raise ValueError("Question is required.")

    mcp_url = build_mcp_url(project_ref)
    deps = SqlAgentDeps(metadata=metadata, mcp_url=mcp_url)

    last_sql: Optional[str] = None

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
    async with agent:
        result = await agent.run(
            question.strip(),
            deps=deps,
            toolsets=[server],
            message_history=history,
        )

    return {"answer": str(result.output), "sql": last_sql}
