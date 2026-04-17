"""Multi-agent workspace: discovery, `expert.toml`, and active-agent state.

A *workspace* is the repository (or subtree) that hosts one or more agent
schemas. The CLI supports three equivalent ways of pointing a command at a
specific agent inside a multi-agent workspace:

1. **Explicit flag** — ``expert ask --agent derm "hi"``.
2. **Positional `@alias`** — ``expert @derm ask "hi"`` (intercepted in
   ``main.py`` and rewritten into the flag above, transparently).
3. **Active pointer** — ``expert use derm`` persists a pointer in
   ``.expert/state.json`` so subsequent ``expert ask "..."`` calls in that
   cwd stay on ``derm`` until the user runs ``expert use`` again.

When none of these disambiguate an unambiguous single agent, commands raise
:class:`AmbiguousAgentError` with a helpful message listing the candidates.

## Discovery

Workspace detection walks up from ``cwd`` looking for the first parent that
contains **any** of these markers:

- ``expert.toml`` (explicit, strongest signal — anchors the workspace).
- ``.expert/state.json`` (previously `expert use`-d directory).
- a sibling pattern of ``*/agent_schema.yaml`` (multi-agent repo by
  convention).

If none is found the workspace defaults to a *single-agent* mode rooted at
cwd, preserving the historical behaviour (``./agent_schema.yaml``).

## ``expert.toml`` schema

```toml
# Optional per-workspace defaults.
[defaults]
agent = "ecg"      # Default agent when no flag / active pointer is set.

# One section per agent. The key becomes the canonical name.
[agents.ecg]
schema      = "ecg-expert/agent_schema.yaml"   # Required. Relative to this file.
endpoint    = "https://ecg-xxx.a.run.app"      # Optional override.
api_key_env = "ECG_ADMIN_KEY"                  # Optional. Takes precedence over api_key.
api_key     = "..."                            # Optional, discouraged (use env).
description = "ECG-specialist clinical agent."  # Optional free-form.

[agents.derm]
schema = "derm-expert/agent_schema.yaml"
```

Any agent that is **auto-discovered** via ``*/agent_schema.yaml`` but not
explicitly declared in ``expert.toml`` is still selectable by its directory
name, and inherits endpoint/api_key from the global ``EXPERT_AGENT_*`` env
vars.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_DIR = ".expert"
_STATE_FILE = "state.json"
_WORKSPACE_FILE = "expert.toml"
_SCHEMA_FILENAME = "agent_schema.yaml"
_DISCOVERY_MAX_DEPTH = 3
_ENV_ACTIVE_AGENT = "EXPERT_AGENT"


class WorkspaceError(RuntimeError):
    """Base for workspace-related errors. Carries an exit-code hint."""

    exit_code: int = 1


class AgentNotFoundError(WorkspaceError):
    """Raised when the caller names an agent that doesn't exist in the workspace."""


class AmbiguousAgentError(WorkspaceError):
    """Raised when a selector matches zero, or more than one, agents.

    ``candidates`` holds every known agent so callers can render a helpful
    prompt/error with the available options.
    """

    def __init__(self, message: str, *, candidates: list[AgentInfo]) -> None:
        super().__init__(message)
        self.candidates = candidates


@dataclass(frozen=True)
class AgentInfo:
    """Metadata about an agent known to the workspace (pre-resolution)."""

    name: str
    schema_path: Path
    endpoint: str | None = None
    api_key: str | None = None
    description: str | None = None
    # "toml" — declared in expert.toml; "auto" — discovered by convention.
    source: str = "auto"


@dataclass(frozen=True)
class AgentContext:
    """Fully-resolved agent context a command can rely on.

    ``api_key`` / ``endpoint`` may still be ``None`` if the agent is offline
    (e.g. for ``expert validate`` which only needs the schema). Commands that
    require remote access should call :meth:`require_remote` instead of
    reading the fields directly.
    """

    name: str
    schema_path: Path
    endpoint: str | None
    api_key: str | None
    description: str | None
    selector_source: str  # "flag", "@alias", "active", "env", "default", "auto", "single"

    def require_remote(self) -> tuple[str, str]:
        """Return ``(endpoint, api_key)``, raising a user-friendly error if missing."""
        if not self.endpoint or not self.api_key:
            raise WorkspaceError(
                f"Agent '{self.name}' has no endpoint/api_key configured. "
                "Set EXPERT_AGENT_ENDPOINT + EXPERT_AGENT_API_KEY, or declare "
                "them in expert.toml under [agents."
                f"{self.name}]."
            )
        return self.endpoint.rstrip("/"), self.api_key


@dataclass
class Workspace:
    """Discovered multi-agent workspace rooted at ``root``."""

    root: Path
    agents_by_name: dict[str, AgentInfo] = field(default_factory=dict)
    default_agent: str | None = None
    # True when no expert.toml AND no sibling schemas found — legacy single-agent mode.
    single_agent_mode: bool = False

    @classmethod
    def discover(cls, *, cwd: Path | None = None) -> Workspace:
        """Discover the workspace rooted at (or above) ``cwd``."""
        start = (cwd or Path.cwd()).resolve()
        root, toml_path = _find_workspace_root(start)
        ws = cls(root=root)

        if toml_path is not None:
            ws._load_toml(toml_path)

        # Auto-discover siblings regardless of whether a TOML exists — the TOML
        # only adds aliases/metadata, it doesn't preclude extra agents shipped
        # in sibling dirs.
        ws._discover_siblings()

        if not ws.agents_by_name:
            # Legacy single-agent mode: one schema next to the user's cwd.
            local = start / _SCHEMA_FILENAME
            if local.is_file():
                ws.agents_by_name["."] = AgentInfo(
                    name=".",
                    schema_path=local,
                    source="single",
                )
                ws.single_agent_mode = True

        return ws

    # --------------------------- TOML loading --------------------------- #

    def _load_toml(self, path: Path) -> None:
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:  # pragma: no cover - rare
            raise WorkspaceError(f"failed to parse {path}: {exc}") from exc

        defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
        default_name = defaults.get("agent") if isinstance(defaults, dict) else None
        if isinstance(default_name, str):
            self.default_agent = default_name

        agents_section = raw.get("agents") if isinstance(raw.get("agents"), dict) else {}
        if not isinstance(agents_section, dict):
            return

        for name, body in agents_section.items():
            if not isinstance(name, str) or not isinstance(body, dict):
                continue
            schema_rel = body.get("schema")
            if not isinstance(schema_rel, str) or not schema_rel:
                raise WorkspaceError(f"expert.toml: agent '{name}' is missing a 'schema' field.")
            schema_abs = (path.parent / schema_rel).resolve()
            api_key = _resolve_api_key(body)
            self.agents_by_name[name] = AgentInfo(
                name=name,
                schema_path=schema_abs,
                endpoint=_opt_str(body.get("endpoint")),
                api_key=api_key,
                description=_opt_str(body.get("description")),
                source="toml",
            )

    # --------------------------- Auto-discovery ------------------------- #

    def _discover_siblings(self) -> None:
        """Walk immediate children of ``root`` for ``*/agent_schema.yaml``."""
        if not self.root.is_dir():
            return
        for child in sorted(self.root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            schema = child / _SCHEMA_FILENAME
            if not schema.is_file():
                continue
            # Skip if already declared via TOML under a different key — the
            # TOML entry is authoritative for that schema.
            if any(info.schema_path == schema for info in self.agents_by_name.values()):
                continue
            # Skip if the directory name collides with a declared TOML name;
            # declared ones win.
            if child.name in self.agents_by_name:
                continue
            self.agents_by_name[child.name] = AgentInfo(
                name=child.name,
                schema_path=schema,
                source="auto",
            )

    # --------------------------- State file ----------------------------- #

    @property
    def state_file(self) -> Path:
        return self.root / _STATE_DIR / _STATE_FILE

    def active(self) -> str | None:
        """Return the agent name pinned via ``expert use``, if any."""
        path = self.state_file
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        name = data.get("agent") if isinstance(data, dict) else None
        return name if isinstance(name, str) else None

    def set_active(self, name: str) -> None:
        if name not in self.agents_by_name:
            raise AgentNotFoundError(
                f"Unknown agent '{name}'. Run `expert agents` to list candidates."
            )
        path = self.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"agent": name}, indent=2) + "\n")

    def clear_active(self) -> None:
        path = self.state_file
        if path.is_file():
            path.unlink()

    # --------------------------- Listing -------------------------------- #

    def agents(self) -> list[AgentInfo]:
        return sorted(self.agents_by_name.values(), key=lambda a: a.name)

    # --------------------------- Resolution ----------------------------- #

    def resolve(
        self,
        selector: str | None = None,
        *,
        env: dict[str, str] | None = None,
        schema_override: Path | None = None,
    ) -> AgentContext:
        """Return a fully-resolved :class:`AgentContext`.

        Resolution order (first match wins):

        1. Explicit ``selector`` (from ``--agent`` or ``@alias``).
        2. ``EXPERT_AGENT`` env var.
        3. ``.expert/state.json`` (set by ``expert use``).
        4. ``[defaults] agent = "..."`` in ``expert.toml``.
        5. Exactly-one-agent short-circuit.
        6. ``schema_override`` (``--schema`` flag, purely file-based fallback).

        Fails with :class:`AmbiguousAgentError` otherwise.
        """
        env = env if env is not None else dict(os.environ)
        source: str
        name: str | None = None

        # An explicit --schema path short-circuits resolution entirely:
        # the caller is telling us "use this file, don't touch the
        # workspace". This mirrors the pre-multi-agent CLI behaviour.
        if schema_override is not None and selector is None:
            return AgentContext(
                name=schema_override.parent.name or ".",
                schema_path=schema_override.resolve(),
                endpoint=env.get("EXPERT_AGENT_ENDPOINT"),
                api_key=env.get("EXPERT_AGENT_API_KEY"),
                description=None,
                selector_source="schema-flag",
            )

        if selector:
            name, source = self._match(selector), "flag"
        elif env.get(_ENV_ACTIVE_AGENT):
            name, source = self._match(env[_ENV_ACTIVE_AGENT]), "env"
        elif (pinned := self.active()) is not None:
            name, source = self._match(pinned), "active"
        elif self.default_agent is not None:
            name, source = self._match(self.default_agent), "default"
        elif len(self.agents_by_name) == 1:
            name, source = (
                next(iter(self.agents_by_name)),
                ("single" if self.single_agent_mode else "auto"),
            )

        if name is None:
            raise AmbiguousAgentError(
                self._ambiguity_message(selector, env),
                candidates=self.agents(),
            )

        info = self.agents_by_name[name]
        endpoint = info.endpoint or env.get("EXPERT_AGENT_ENDPOINT")
        api_key = info.api_key or env.get("EXPERT_AGENT_API_KEY")
        schema_path = schema_override.resolve() if schema_override else info.schema_path
        return AgentContext(
            name=info.name,
            schema_path=schema_path,
            endpoint=endpoint,
            api_key=api_key,
            description=info.description,
            selector_source=source,
        )

    # --------------------------- Internals ------------------------------ #

    def _match(self, selector: str) -> str:
        """Resolve an agent selector (exact name or unique prefix).

        Accepts and strips a leading ``@`` so that the same helper can back
        both ``--agent derm`` and ``@derm`` transparently.
        """
        if not selector:
            raise AgentNotFoundError("empty agent selector")
        needle = selector.lstrip("@")
        if needle in self.agents_by_name:
            return needle
        matches = [n for n in self.agents_by_name if n.startswith(needle)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise AgentNotFoundError(
                f"No agent named '{needle}'. "
                f"Available: {', '.join(sorted(self.agents_by_name)) or '(none)'}."
            )
        raise AmbiguousAgentError(
            f"Prefix '{needle}' is ambiguous — matches: {', '.join(sorted(matches))}. "
            "Use the full name or a longer prefix.",
            candidates=[self.agents_by_name[m] for m in matches],
        )

    def _ambiguity_message(self, selector: str | None, env: dict[str, str]) -> str:
        if not self.agents_by_name:
            return (
                "No agent_schema.yaml found in this workspace. "
                "Run `expert init <name>` to scaffold one, or pass "
                "--schema explicitly."
            )
        lines = [
            "Multiple agents found in this workspace and no selector was given.",
            "",
            "Candidates:",
        ]
        for info in self.agents():
            rel = _safe_relpath(info.schema_path, self.root)
            badge = "[toml]" if info.source == "toml" else "[auto]"
            lines.append(f"  • {info.name:<20} {rel}  {badge}")
        lines.extend(
            [
                "",
                "Pick one, in order of preference:",
                "  expert @<name> <command>          # one-off shortcut",
                "  expert <command> --agent <name>   # explicit flag (CI-friendly)",
                "  expert use <name>                 # pin for this workspace",
            ]
        )
        _ = selector, env
        return "\n".join(lines)


# ------------------------------------------------------------------------- #
# Helpers
# ------------------------------------------------------------------------- #


def _find_workspace_root(start: Path) -> tuple[Path, Path | None]:
    """Walk up from ``start`` to find a workspace root + optional TOML path.

    Returns ``(root, toml_path)`` where ``toml_path`` may be ``None``. The
    ``root`` is:

    - The first ancestor containing ``expert.toml`` (authoritative marker).
    - Else the first ancestor containing ``.expert/state.json`` (previously
      pinned via ``expert use``).
    - Else ``start`` itself. Sibling-schema discovery is always rooted at
      ``start`` — we never silently promote an unrelated ancestor to
      ``root`` just because it happens to have other agent directories
      lying around.
    """
    current = start
    for _ in range(_DISCOVERY_MAX_DEPTH + 1):
        toml = current / _WORKSPACE_FILE
        if toml.is_file():
            return current, toml
        if (current / _STATE_DIR / _STATE_FILE).is_file():
            return current, None
        if current.parent == current:
            break
        current = current.parent
    return start, None


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _resolve_api_key(body: dict[str, Any]) -> str | None:
    env_var = body.get("api_key_env")
    if isinstance(env_var, str) and env_var:
        env_value = os.environ.get(env_var)
        if env_value:
            return env_value
    raw = body.get("api_key")
    return raw if isinstance(raw, str) and raw else None


def _safe_relpath(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


__all__ = [
    "AgentContext",
    "AgentInfo",
    "AgentNotFoundError",
    "AmbiguousAgentError",
    "Workspace",
    "WorkspaceError",
]
