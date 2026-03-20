import os
from typing import Optional

from langfuse.openai import openai as langfuse_openai
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider


_OPENAI_PROVIDER: Optional[OpenAIProvider] = None


def _get_openai_provider() -> OpenAIProvider:
    global _OPENAI_PROVIDER
    if _OPENAI_PROVIDER is not None:
        return _OPENAI_PROVIDER
    openai_client = langfuse_openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    _OPENAI_PROVIDER = OpenAIProvider(openai_client=openai_client)
    return _OPENAI_PROVIDER


def build_openai_model(model_name: str) -> OpenAIModel:
    return OpenAIModel(model_name, provider=_get_openai_provider())
