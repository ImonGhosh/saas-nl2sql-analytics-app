import time
from typing import Any, Dict, Optional

from langfuse_client import get_langfuse_client


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def start_trace(
    *,
    trace_id: Optional[str],
    name: Optional[str],
    user_id: Optional[str],
    session_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> Optional[Any]:
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        return client.trace(
            id=trace_id,
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
        )
    except Exception:
        return None


def start_span(
    trace: Optional[Any],
    *,
    name: str,
    metadata: Optional[Dict[str, Any]] = None,
    input: Optional[Any] = None,
) -> Optional[Any]:
    if trace is None:
        return None
    try:
        if input is None:
            return trace.span(name=name, metadata=metadata)
        return trace.span(name=name, metadata=metadata, input=input)
    except Exception:
        return None


def end_span(
    span: Optional[Any],
    *,
    metadata: Optional[Dict[str, Any]] = None,
    output: Optional[Any] = None,
    error: Optional[str] = None,
) -> None:
    if span is None:
        return
    payload: Dict[str, Any] = {}
    if metadata is not None:
        payload["metadata"] = metadata
    if output is not None:
        payload["output"] = output
    if error is not None:
        payload["error"] = error
    for method in ("end", "update"):
        fn = getattr(span, method, None)
        if callable(fn):
            try:
                fn(**payload)
            except Exception:
                pass
            break


def extract_prompt_tokens(result: Any) -> Optional[int]:
    usage = getattr(result, "usage", None)
    if callable(usage):
        try:
            usage = usage()
        except Exception:
            usage = None
    if isinstance(usage, dict):
        for key in ("prompt_tokens", "input_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                return value
    for attr in ("prompt_tokens", "input_tokens"):
        value = getattr(usage, attr, None)
        if isinstance(value, int):
            return value
    return None
