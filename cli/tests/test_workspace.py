"""Tests for multi-agent workspace discovery and resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from expert.workspace import (
    AgentNotFoundError,
    AmbiguousAgentError,
    Workspace,
    WorkspaceError,
)

# ------------------------------------------------------------------------- #
# Fixtures
# ------------------------------------------------------------------------- #


def _mk_schema(dir_: Path, name: str = "a") -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    f = dir_ / "agent_schema.yaml"
    f.write_text(f"# dummy schema for {name}\n")
    return f


def _mk_workspace(
    root: Path,
    *,
    agents: dict[str, dict[str, object]] | None = None,
    default: str | None = None,
) -> None:
    """Create a workspace directory with optional expert.toml.

    ``agents`` maps canonical names to dicts of ``schema``/``endpoint``/etc.
    Schemas are materialised on disk relative to ``root``.
    """
    if agents is None:
        return
    lines: list[str] = []
    if default:
        lines.extend(["[defaults]", f'agent = "{default}"', ""])
    for name, body in agents.items():
        schema_rel = body.get("schema") or f"{name}/agent_schema.yaml"
        assert isinstance(schema_rel, str)
        _mk_schema(root / Path(schema_rel).parent, name=name)
        lines.append(f"[agents.{name}]")
        lines.append(f'schema = "{schema_rel}"')
        for key in ("endpoint", "api_key", "api_key_env", "description"):
            value = body.get(key)
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
        lines.append("")
    (root / "expert.toml").write_text("\n".join(lines))


# ------------------------------------------------------------------------- #
# Discovery
# ------------------------------------------------------------------------- #


def test_single_agent_mode(tmp_path: Path) -> None:
    _mk_schema(tmp_path)
    ws = Workspace.discover(cwd=tmp_path)
    assert ws.single_agent_mode is True
    assert list(ws.agents_by_name) == ["."]

    ctx = ws.resolve()
    assert ctx.name == "."
    assert ctx.selector_source == "single"


def test_auto_discover_siblings(tmp_path: Path) -> None:
    _mk_schema(tmp_path / "my-expert")
    _mk_schema(tmp_path / "derm")
    ws = Workspace.discover(cwd=tmp_path)
    assert ws.single_agent_mode is False
    assert set(ws.agents_by_name) == {"my-expert", "derm"}
    assert all(info.source == "auto" for info in ws.agents())


def test_toml_overrides_auto(tmp_path: Path) -> None:
    _mk_workspace(
        tmp_path,
        agents={
            "my-expert": {"schema": "my-expert/agent_schema.yaml", "endpoint": "https://my-expert"},
            "derm": {"schema": "derm/agent_schema.yaml"},
        },
        default="my-expert",
    )
    ws = Workspace.discover(cwd=tmp_path)
    assert ws.default_agent == "my-expert"
    assert ws.agents_by_name["my-expert"].source == "toml"
    assert ws.agents_by_name["my-expert"].endpoint == "https://my-expert"


def test_toml_plus_sibling_not_declared(tmp_path: Path) -> None:
    """Declared agents + undeclared siblings should coexist."""
    _mk_workspace(
        tmp_path,
        agents={"my-expert": {"schema": "my-expert/agent_schema.yaml"}},
    )
    _mk_schema(tmp_path / "derm")
    ws = Workspace.discover(cwd=tmp_path)
    assert set(ws.agents_by_name) == {"my-expert", "derm"}
    assert ws.agents_by_name["my-expert"].source == "toml"
    assert ws.agents_by_name["derm"].source == "auto"


# ------------------------------------------------------------------------- #
# Resolution precedence
# ------------------------------------------------------------------------- #


def test_resolve_explicit_selector_wins(tmp_path: Path) -> None:
    _mk_workspace(
        tmp_path,
        agents={"my-expert": {}, "derm": {}},
        default="my-expert",
    )
    ws = Workspace.discover(cwd=tmp_path)
    ws.set_active("my-expert")
    ctx = ws.resolve(selector="derm")
    assert ctx.name == "derm"
    assert ctx.selector_source == "flag"


def test_resolve_env_var(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(env={"EXPERT_AGENT": "derm"})
    assert ctx.name == "derm"
    assert ctx.selector_source == "env"


def test_resolve_active_pin(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ws.set_active("derm")
    ctx = ws.resolve(env={})
    assert ctx.name == "derm"
    assert ctx.selector_source == "active"


def test_resolve_default_from_toml(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}}, default="my-expert")
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(env={})
    assert ctx.name == "my-expert"
    assert ctx.selector_source == "default"


def test_resolve_ambiguous(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}})
    ws = Workspace.discover(cwd=tmp_path)
    with pytest.raises(AmbiguousAgentError) as exc_info:
        ws.resolve(env={})
    assert "Multiple agents" in str(exc_info.value)
    names = {c.name for c in exc_info.value.candidates}
    assert names == {"my-expert", "derm"}


def test_resolve_unique_prefix(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(selector="my")
    assert ctx.name == "my-expert"


def test_resolve_ambiguous_prefix(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "my-trainer": {}})
    ws = Workspace.discover(cwd=tmp_path)
    with pytest.raises(AmbiguousAgentError):
        ws.resolve(selector="my")


def test_resolve_unknown_selector(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}})
    ws = Workspace.discover(cwd=tmp_path)
    with pytest.raises(AgentNotFoundError):
        ws.resolve(selector="nope")


def test_resolve_at_alias_prefix_strip(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(selector="@my-expert")
    assert ctx.name == "my-expert"


def test_resolve_schema_override_bypasses_workspace(tmp_path: Path) -> None:
    standalone = tmp_path / "orphan"
    schema = _mk_schema(standalone)
    # No workspace here — ensure the flag-based fallback works.
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(schema_override=schema, env={})
    assert ctx.schema_path == schema
    assert ctx.selector_source == "schema-flag"


# ------------------------------------------------------------------------- #
# API key resolution
# ------------------------------------------------------------------------- #


def test_api_key_from_env_via_api_key_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_EXPERT_KEY", "sk-from-env")
    _mk_workspace(
        tmp_path,
        agents={
            "my-expert": {
                "schema": "my-expert/agent_schema.yaml",
                "api_key_env": "MY_EXPERT_KEY",
            }
        },
    )
    ws = Workspace.discover(cwd=tmp_path)
    assert ws.agents_by_name["my-expert"].api_key == "sk-from-env"


def test_env_endpoint_fills_when_toml_missing(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(env={"EXPERT_AGENT_ENDPOINT": "https://x", "EXPERT_AGENT_API_KEY": "k"})
    assert ctx.endpoint == "https://x"
    assert ctx.api_key == "k"


def test_require_remote_raises_when_incomplete(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ctx = ws.resolve(env={})
    with pytest.raises(WorkspaceError):
        ctx.require_remote()


# ------------------------------------------------------------------------- #
# Pin state file
# ------------------------------------------------------------------------- #


def test_set_active_writes_state(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}, "derm": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ws.set_active("derm")
    state = json.loads(ws.state_file.read_text())
    assert state == {"agent": "derm"}
    assert ws.active() == "derm"


def test_clear_active(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}})
    ws = Workspace.discover(cwd=tmp_path)
    ws.set_active("my-expert")
    ws.clear_active()
    assert ws.active() is None


def test_set_active_rejects_unknown(tmp_path: Path) -> None:
    _mk_workspace(tmp_path, agents={"my-expert": {}})
    ws = Workspace.discover(cwd=tmp_path)
    with pytest.raises(AgentNotFoundError):
        ws.set_active("nope")
