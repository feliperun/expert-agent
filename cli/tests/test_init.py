"""Tests for `agent-cli init`."""

from __future__ import annotations

from pathlib import Path

from agent_cli.main import app
from app.schema import AgentSchema
from typer.testing import CliRunner


def test_init_scaffolds_project(tmp_path: Path) -> None:
    runner = CliRunner()
    dest = tmp_path / "my-test-agent"
    result = runner.invoke(
        app,
        ["init", str(dest)],
        input="my-test-agent\nTest agent description.\n",
    )
    assert result.exit_code == 0, result.output

    schema_path = dest / "agent_schema.yaml"
    identity_path = dest / "prompts" / "identity.md"
    docs_keep = dest / "docs" / ".gitkeep"
    readme = dest / "README.md"

    assert schema_path.is_file()
    assert identity_path.is_file()
    assert docs_keep.is_file()
    assert readme.is_file()

    schema = AgentSchema.from_yaml(schema_path)
    assert schema.metadata.name == "my-test-agent"
    assert schema.metadata.description == "Test agent description."
    assert schema.spec.identity.system_prompt_file == Path("./prompts/identity.md")


def test_init_refuses_overwrite_without_force(tmp_path: Path) -> None:
    runner = CliRunner()
    dest = tmp_path / "existing"
    dest.mkdir()
    (dest / "agent_schema.yaml").write_text("preexisting: true\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["init", str(dest)],
        input="existing\nDescription.\n",
    )
    assert result.exit_code == 1, result.output
    assert "--force" in result.output


def test_init_rejects_invalid_name(tmp_path: Path) -> None:
    runner = CliRunner()
    dest = tmp_path / "my-agent"
    result = runner.invoke(
        app,
        ["init", str(dest)],
        input="Invalid_Name\nvalid-name\nDescription.\n",
    )
    assert result.exit_code == 0, result.output
    assert "ERROR" in result.output
    schema = AgentSchema.from_yaml(dest / "agent_schema.yaml")
    assert schema.metadata.name == "valid-name"
