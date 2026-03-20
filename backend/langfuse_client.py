import os
from typing import Optional

try:
    from langfuse import Langfuse
except Exception:
    Langfuse = None  # type: ignore[assignment]


_CLIENT: Optional["Langfuse"] = None


def get_langfuse_client() -> Optional["Langfuse"]:
    """Return a singleton Langfuse client if configured, otherwise None."""
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    if Langfuse is None:
        return None

    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")
    if not secret_key or not public_key:
        return None

    kwargs = {"public_key": public_key, "secret_key": secret_key}
    if host:
        kwargs["host"] = host

    _CLIENT = Langfuse(**kwargs)
    return _CLIENT
