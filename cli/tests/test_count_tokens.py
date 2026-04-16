"""Tests for `agent-cli count-tokens`."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_cli.commands import count_tokens
from agent_cli.main import app
from typer.testing import CliRunner

SCHEMA_TEMPLATE = """\
apiVersion: expert-agent/v1
kind: AgentSchema
metadata:
  name: test-agent
spec:
  identity:
    system_prompt: "You are a helper."
  knowledge:
    reference_docs_dir: ./docs
    include_patterns:
      - "*.md"
"""


def _seed_project(tmp_path: Path) -> Path:
    schema = tmp_path / "agent_schema.yaml"
    schema.write_text(SCHEMA_TEMPLATE, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("hello world", encoding="utf-8")
    (docs / "b.md").write_text("another document with more words", encoding="utf-8")
    return schema


def test_count_tokens_sums_across_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = _seed_project(tmp_path)

    per_call_tokens = [7, 42]
    call_index = {"n": 0}

    async def fake_count(*, model: str, contents: Any) -> Any:
        idx = call_index["n"]
        call_index["n"] += 1
        response = MagicMock()
        response.total_tokens = per_call_tokens[idx]
        return response

    fake_client = MagicMock()
    fake_client.aio.models.count_tokens = AsyncMock(side_effect=fake_count)

    monkeypatch.setattr(count_tokens, "_make_client", lambda api_key: fake_client)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "count-tokens",
            "--schema",
            str(schema),
            "--gemini-api-key",
            "test-key",
            "--model",
            "gemini-2.0-flash-exp",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "49" in result.output
    assert fake_client.aio.models.count_tokens.await_count == 2


def test_count_tokens_warns_on_large_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = _seed_project(tmp_path)

    async def fake_count(*, model: str, contents: Any) -> Any:
        response = MagicMock()
        response.total_tokens = 500_000
        return response

    fake_client = MagicMock()
    fake_client.aio.models.count_tokens = AsyncMock(side_effect=fake_count)
    monkeypatch.setattr(count_tokens, "_make_client", lambda api_key: fake_client)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "count-tokens",
            "--schema",
            str(schema),
            "--gemini-api-key",
            "k",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "sweet spot" in result.output.lower()
