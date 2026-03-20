import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from langfuse_tracing import end_span, extract_prompt_tokens, start_span, start_trace
from llm_provider import build_openai_model

class ChartSuggestions(BaseModel):
    suggestions: List[str] = Field(
        default_factory=list,
        description="Concise chart ideas grounded in the metadata.",
    )


@dataclass
class ChartSuggestionsDeps:
    metadata: Dict[str, Any]


_SUGGESTIONS_AGENT: Agent | None = None


def _get_suggestions_model() -> str:
    model = os.getenv("CHART_SUGGESTIONS_MODEL") or os.getenv("SQL_AGENT_MODEL")
    if not model:
        raise RuntimeError("CHART_SUGGESTIONS_MODEL (or SQL_AGENT_MODEL) is not set.")
    return model


def _get_suggestions_agent() -> Agent:
    global _SUGGESTIONS_AGENT
    if _SUGGESTIONS_AGENT is not None:
        return _SUGGESTIONS_AGENT

    model_name = _get_suggestions_model()
    model = build_openai_model(model_name)
    _SUGGESTIONS_AGENT = Agent(
        model,
        deps_type=ChartSuggestionsDeps,
        instructions=(
            "You are an analytics suggestions agent. "
            "Generate exactly 5 concise chart ideas based only on the provided database metadata. "
            "Each suggestion should be 6-12 words, describe a KPI or chart, and focus on real-world impact "
            "(e.g revenue, growth, churn, retention, usage, operations). "
            "Avoid vague phrasing and do not invent tables or columns. "
            "Return suggestions as an array of strings."
        ),
        output_type=ChartSuggestions,
    )

    @_SUGGESTIONS_AGENT.instructions
    def add_metadata(ctx: RunContext[ChartSuggestionsDeps]) -> str:
        metadata_json = json.dumps(ctx.deps.metadata, indent=2, sort_keys=True)
        return f"Database metadata:\n{metadata_json}"

    return _SUGGESTIONS_AGENT


async def run_chart_suggestions_agent(
    *,
    metadata: Dict[str, Any],
    trace_id: Optional[str] = None,
    trace_name: Optional[str] = None,
    trace_user_id: Optional[str] = None,
    trace_session_id: Optional[str] = None,
    trace_metadata: Optional[Dict[str, Any]] = None,
) -> ChartSuggestions:
    agent = _get_suggestions_agent()
    deps = ChartSuggestionsDeps(metadata=metadata)
    trace = start_trace(
        trace_id=trace_id,
        name=trace_name,
        user_id=trace_user_id,
        session_id=trace_session_id,
        metadata=trace_metadata,
    )
    span_metadata: Dict[str, Any] = {"model": _get_suggestions_model()}
    span = start_span(trace, name="chart_suggestions_agent.run", metadata=span_metadata)
    start_ms = time.perf_counter()
    try:
        async with agent:
            result = await agent.run(
                "Create concise chart suggestions based on the metadata.",
                deps=deps,
            )
        prompt_tokens = extract_prompt_tokens(result)
        if prompt_tokens is not None:
            span_metadata["prompt_tokens"] = prompt_tokens
        span_metadata["latency_ms"] = round((time.perf_counter() - start_ms) * 1000, 2)
        span_metadata["success"] = True
        end_span(span, metadata=span_metadata)
    except Exception as exc:
        span_metadata["latency_ms"] = round((time.perf_counter() - start_ms) * 1000, 2)
        span_metadata["success"] = False
        span_metadata["error"] = str(exc)
        end_span(span, metadata=span_metadata, error=str(exc))
        raise
    return result.output
