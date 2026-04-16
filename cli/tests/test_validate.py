"""Tests for `agent-cli validate`."""

from __future__ import annotations

import shutil
from pathlib import Path

from agent_cli.main import app
from typer.testing import CliRunner

EXAMPLE_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "example-schema"


def _seed_workdir(tmp_path: Path) -> Path:
    """Clone `example-schema/` into `tmp_path` and seed a reference doc."""
    dest = tmp_path / "agent"
    shutil.copytree(EXAMPLE_SCHEMA_DIR, dest)
    docs = dest / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "intro.md").write_text(
        "# Intro\n\nAn example reference document.\n",
        encoding="utf-8",
    )
    (docs / "details.md").write_text(
        "# Details\n\nMore context for the specialist agent.\n",
        encoding="utf-8",
    )
    (docs / "extra.md").write_text(
        "# Extra\n\nEven more material.\n",
        encoding="utf-8",
    )
    return dest


def test_validate_success_on_example_schema(tmp_path: Path) -> None:
    runner = CliRunner()
    dest = _seed_workdir(tmp_path)
    result = runner.invoke(app, ["validate", "--schema", str(dest / "agent_schema.yaml")])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output.lower()


def test_validate_missing_schema_file(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["validate", "--schema", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_validate_broken_schema(tmp_path: Path) -> None:
    runner = CliRunner()
    schema_file = tmp_path / "agent_schema.yaml"
    schema_file.write_text(
        "apiVersion: expert-agent/v1\n"
        "kind: AgentSchema\n"
        "metadata:\n"
        "  name: Invalid_Name\n"
        "spec:\n"
        "  identity:\n"
        "    system_prompt: 'x'\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--schema", str(schema_file)])
    assert result.exit_code == 1
    assert "validation failed" in result.output.lower()


def test_validate_missing_docs_dir(tmp_path: Path) -> None:
    runner = CliRunner()
    schema_file = tmp_path / "agent_schema.yaml"
    schema_file.write_text(
        "apiVersion: expert-agent/v1\n"
        "kind: AgentSchema\n"
        "metadata:\n"
        "  name: test-agent\n"
        "spec:\n"
        "  identity:\n"
        "    system_prompt: 'You are a helper.'\n"
        "  knowledge:\n"
        "    reference_docs_dir: ./does-not-exist\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", "--schema", str(schema_file)])
    assert result.exit_code == 1
    assert "does not exist" in result.output.lower()
