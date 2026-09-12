"""
Single place that decides which LLMProvider gets constructed.

Everything downstream (the RAG pipeline, the API routes) calls
get_llm_provider() and never imports a concrete provider class.
Change the model under test by editing .env, not code.
"""

import os

from .anthropic_provider import AnthropicProvider
from .base import LLMProvider
from .groq_provider import GroqProvider
from .local_provider import LocalProvider
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider

_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "local": LocalProvider,
    "mock": MockProvider,
}


def get_llm_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    provider_name = name or os.environ.get("LLM_PROVIDER", "anthropic")

    if provider_name not in _PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider '{provider_name}'. Options: {list(_PROVIDERS)}"
        )

    kwargs = {}
    if model:
        kwargs["model"] = model
    elif env_model := os.environ.get("LLM_MODEL"):
        kwargs["model"] = env_model

    return _PROVIDERS[provider_name](**kwargs)
