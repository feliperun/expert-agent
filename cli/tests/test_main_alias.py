"""Tests for the `@alias` argv rewriter and workspace-aware commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from expert.main import _rewrite_at_alias, app
from typer.testing import CliRunner


def test_rewrite_at_alias_for_agent_aware_subcommand() -> None:
    argv = ["expert", "@my-expert", "ask", "hi", "--no-stream"]
    assert _rewrite_at_alias(argv) == [
        "expert",
        "ask",
        "hi",
        "--no-stream",
        "--agent",
        "my-expert",
    ]


def test_rewrite_at_alias_preserves_nested_subcommand() -> None:
    argv = ["expert", "@derm", "sessions", "list"]
    assert _rewrite_at_alias(argv) == [
        "expert",
        "sessions",
        "list",
        "--agent",
        "derm",
    ]


def test_rewrite_at_alias_no_rewrite_for_non_agent_command() -> None:
    """`use`/`agents` aren't in the allow-list; argv is returned unchanged."""
    argv = ["expert", "@my-expert", "use", "my-expert"]
    assert _rewrite_at_alias(argv) == argv


def test_rewrite_at_alias_no_arg_after() -> None:
    """`expert @my-expert` with nothing else is left alone (Typer will show help)."""
    argv = ["expert", "@my-expert"]
    assert _rewrite_at_alias(argv) == argv


def test_rewrite_ignores_dashed_tokens_between_alias_and_subcommand() -> None:
    argv = ["expert", "@my-expert", "--verbose", "validate"]
    assert _rewrite_at_alias(argv) == [
        "expert",
        "--verbose",
        "validate",
        "--agent",
        "my-expert",
    ]


def test_rewrite_appends_agent_at_end_for_sessions_list() -> None:
    """Appending at the end routes the flag to the deepest sub-Typer."""
    argv = ["expert", "@derm", "sessions", "list", "--user", "u1"]
    assert _rewrite_at_alias(argv) == [
        "expert",
        "sessions",
        "list",
        "--user",
        "u1",
        "--agent",
        "derm",
    ]


def test_rewrite_handles_empty_alias() -> None:
    argv = ["expert", "@", "ask", "hi"]
    # Too short — should no-op rather than misinterpret.
    assert _rewrite_at_alias(argv) == argv


# ------------------------------------------------------------------------- #
# Integration: workspace-aware commands
# ------------------------------------------------------------------------- #


def _seed(tmp_path: Path) -> Path:
    (tmp_path / "my-expert").mkdir()
    (tmp_path / "derm").mkdir()
    (tmp_path / "my-expert" / "agent_schema.yaml").write_text("x")
    (tmp_path / "derm" / "agent_schema.yaml").write_text("x")
    (tmp_path / "expert.toml").write_text(
        '[defaults]\nagent = "my-expert"\n\n'
        '[agents.my-expert]\nschema = "my-expert/agent_schema.yaml"\n'
        'endpoint = "https://my-expert.example"\napi_key = "sk-test"\n\n'
        '[agents.derm]\nschema = "derm/agent_schema.yaml"\n',
    )
    return tmp_path


def test_agents_command_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["agents"])
    assert result.exit_code == 0, result.output
    assert "my-expert" in result.output
    assert "derm" in result.output


def test_which_uses_toml_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EXPERT_AGENT", raising=False)
    monkeypatch.delenv("EXPERT_AGENT_ENDPOINT", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["which"])
    assert result.exit_code == 0, result.output
    assert "my-expert" in result.output
    assert "default" in result.output


def test_use_then_which(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EXPERT_AGENT", raising=False)
    runner = CliRunner()

    res = runner.invoke(app, ["use", "derm"])
    assert res.exit_code == 0, res.output

    res = runner.invoke(app, ["which"])
    assert res.exit_code == 0, res.output
    assert "derm" in res.output
    assert "active" in res.output


def test_which_with_agent_flag_overrides_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EXPERT_AGENT", raising=False)
    runner = CliRunner()
    runner.invoke(app, ["use", "derm"])
    res = runner.invoke(app, ["which", "--agent", "my-expert"])
    assert res.exit_code == 0, res.output
    assert "my-expert" in res.output
    assert "flag" in res.output


def test_use_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["use", "derm"])
    assert (tmp_path / ".expert" / "state.json").is_file()

    res = runner.invoke(app, ["use", "--clear"])
    assert res.exit_code == 0, res.output
    assert not (tmp_path / ".expert" / "state.json").is_file()


def test_use_unknown_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["use", "does-not-exist"])
    assert res.exit_code != 0


def test_ambiguous_workspace_shows_helpful_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two auto-discovered agents, no selector → helpful multi-line error."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "agent_schema.yaml").write_text("x")
    (tmp_path / "b" / "agent_schema.yaml").write_text("x")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EXPERT_AGENT", raising=False)

    runner = CliRunner()
    res = runner.invoke(app, ["which"])
    assert res.exit_code != 0
    assert "expert @" in res.output or "@<name>" in res.output
    assert "--agent" in res.output
