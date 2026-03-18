import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext


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

    _SUGGESTIONS_AGENT = Agent(
        _get_suggestions_model(),
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
) -> ChartSuggestions:
    agent = _get_suggestions_agent()
    deps = ChartSuggestionsDeps(metadata=metadata)
    async with agent:
        result = await agent.run(
            "Create concise chart suggestions based on the metadata.",
            deps=deps,
        )
    return result.output
