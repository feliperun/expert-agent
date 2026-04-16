from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schema import AgentSchema


EXAMPLE_SCHEMA = (
    Path(__file__).resolve().parents[2] / "example-schema" / "agent_schema.yaml"
)


def test_example_schema_loads() -> None:
    schema = AgentSchema.from_yaml(EXAMPLE_SCHEMA)
    assert schema.apiVersion == "expert-agent/v1"
    assert schema.kind == "AgentSchema"
    assert schema.metadata.name == "example-expert"
    assert schema.spec.model.provider == "gemini"
    assert schema.spec.memory.long_term.persistence.type == "chroma-http"
    assert schema.agent_id == "example-expert"


def test_invalid_agent_name_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSchema.model_validate(
            {
                "apiVersion": "expert-agent/v1",
                "kind": "AgentSchema",
                "metadata": {"name": "Invalid_Name_With_Underscore"},
                "spec": {"identity": {"system_prompt": "x"}},
            }
        )


def test_identity_requires_exactly_one_source() -> None:
    base = {
        "apiVersion": "expert-agent/v1",
        "kind": "AgentSchema",
        "metadata": {"name": "test"},
        "spec": {"identity": {}},
    }
    with pytest.raises(ValidationError):
        AgentSchema.model_validate(base)

    both = {**base, "spec": {"identity": {"system_prompt": "x", "system_prompt_file": "y"}}}
    with pytest.raises(ValidationError):
        AgentSchema.model_validate(both)
