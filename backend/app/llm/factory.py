"""Dispatch an `LLMClient` implementation based on the agent schema."""

from __future__ import annotations

from ..config import Settings
from ..schema import AgentSchema
from .gemini_ai_studio import GeminiAIStudioClient
from .gemini_vertex import GeminiVertexClient
from .protocol import LLMClient


def build_llm_client(schema: AgentSchema, settings: Settings) -> LLMClient:
    """Construct the configured LLM backend.

    The schema selects the provider; `settings` carries credentials.
    """
    provider = schema.spec.model.provider
    model_name = schema.spec.model.name
    max_citations = schema.spec.grounding.max_citations
    thinking_budget = schema.spec.model.thinking_budget

    if provider == "gemini":
        api_key = settings.gemini_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is required when provider=gemini; set the env/secret."
            )
        return GeminiAIStudioClient(
            api_key=api_key,
            model=model_name,
            max_citations=max_citations,
            thinking_budget=thinking_budget,
        )

    if provider == "gemini-vertex":
        return GeminiVertexClient(
            project=settings.gcp_project,
            model=model_name,
            max_citations=max_citations,
        )

    raise ValueError(f"Unsupported LLM provider: {provider!r}")


__all__ = ["build_llm_client"]
