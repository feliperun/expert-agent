"""Pydantic models for the agent schema (`agent_schema.yaml`).

This is the source of truth for the runtime contract. Every agent is defined by
an `agent_schema.yaml` file that deserializes into `AgentSchema`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["gemini", "gemini-vertex"] = "gemini"
    name: str = Field(default="gemini-2.5-pro", min_length=1)
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.3
    max_output_tokens: Annotated[int, Field(ge=256, le=65_536)] = 8_192
    top_p: Annotated[float, Field(ge=0.0, le=1.0)] = 0.95
    # Gemini 2.5 thinking budget (tokens spent on internal reasoning before the
    # answer stream starts). `None` = SDK default (Pro thinks ~a lot).
    # Caps per Google docs:
    #   gemini-2.5-pro       : 128 - 32_768 (cannot be 0)
    #   gemini-2.5-flash     : 0 - 24_576   (0 disables thinking entirely)
    #   gemini-2.5-flash-lite: 512 - 24_576
    # Lower = lower TTFT and cheaper tokens, higher = stronger reasoning.
    thinking_budget: Annotated[int | None, Field(ge=0, le=32_768)] = None


class IdentitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt_file: Path | None = None
    system_prompt: str | None = None

    @model_validator(mode="after")
    def require_one(self) -> IdentitySpec:
        if bool(self.system_prompt_file) == bool(self.system_prompt):
            raise ValueError(
                "identity: provide exactly one of `system_prompt_file` or `system_prompt`"
            )
        return self


class KnowledgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_docs_dir: Path = Field(default=Path("./docs"))
    include_patterns: list[str] = Field(default_factory=lambda: ["*.md", "*.pdf", "*.txt"])
    exclude_patterns: list[str] = Field(default_factory=list)


class ContextCacheSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    ttl_seconds: Annotated[int, Field(ge=60, le=86_400)] = 3_600
    refresh_before_expiry_seconds: Annotated[int, Field(ge=30, le=3_600)] = 300


class ShortTermMemorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buffer_size: Annotated[int, Field(ge=0, le=100)] = 20
    storage: Literal["firestore"] = "firestore"


class LongTermPersistenceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["chroma-http", "chroma-embedded", "firestore-vector", "vertex-vector-search"] = (
        "chroma-http"
    )
    mount_path: Path | None = None
    host: str | None = None
    port: int | None = None
    ssl: bool = True


class LongTermMemorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    engine: Literal["mempalace"] = "mempalace"
    max_recall_results: Annotated[int, Field(ge=0, le=50)] = 5
    persistence: LongTermPersistenceSpec = Field(default_factory=LongTermPersistenceSpec)


class MemorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_term: ShortTermMemorySpec = Field(default_factory=ShortTermMemorySpec)
    long_term: LongTermMemorySpec = Field(default_factory=LongTermMemorySpec)


class GroundingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_citations: Annotated[int, Field(ge=0, le=50)] = 10


class RateLimitSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests_per_minute: Annotated[int, Field(ge=1, le=10_000)] = 30
    tokens_per_day: Annotated[int, Field(ge=1_000, le=100_000_000)] = 1_000_000


class AgentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, pattern=r"^[a-z][a-z0-9-]*$")]
    description: str = ""
    version: str = "0.1.0"

    @field_validator("name")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        if len(v) > 63:
            raise ValueError("agent name must be <= 63 chars (Cloud Run service name limit)")
        return v


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ModelSpec = Field(default_factory=ModelSpec)
    identity: IdentitySpec
    knowledge: KnowledgeSpec = Field(default_factory=KnowledgeSpec)
    context_cache: ContextCacheSpec = Field(default_factory=ContextCacheSpec)
    memory: MemorySpec = Field(default_factory=MemorySpec)
    grounding: GroundingSpec = Field(default_factory=GroundingSpec)
    rate_limit: RateLimitSpec = Field(default_factory=RateLimitSpec)


class AgentSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apiVersion: Literal["expert-agent/v1"] = "expert-agent/v1"  # noqa: N815 — k8s-style field name
    kind: Literal["AgentSchema"] = "AgentSchema"
    metadata: AgentMetadata
    spec: AgentSpec

    @classmethod
    def from_yaml(cls, path: Path | str) -> AgentSchema:
        """Load & validate an agent_schema.yaml."""
        raw = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )

    @property
    def agent_id(self) -> str:
        """Canonical short ID used across GCS prefixes, SA names, Firestore paths."""
        return self.metadata.name


__all__ = [
    "AgentMetadata",
    "AgentSchema",
    "AgentSpec",
    "ContextCacheSpec",
    "GroundingSpec",
    "IdentitySpec",
    "KnowledgeSpec",
    "LongTermMemorySpec",
    "LongTermPersistenceSpec",
    "MemorySpec",
    "ModelSpec",
    "RateLimitSpec",
    "ShortTermMemorySpec",
]
