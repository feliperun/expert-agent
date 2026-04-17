"""Shared helpers used by every command that needs an :class:`AgentContext`.

Commands should call :func:`resolve` at their very top, forward flag-overrides
in, and then read ``ctx.schema_path`` / ``ctx.endpoint`` / ``ctx.api_key``.

This keeps the multi-agent resolution logic in one place — if we ever change
precedence rules, every command picks it up automatically.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import typer

from .ui import print_error
from .workspace import (
    AgentContext,
    AgentNotFoundError,
    AmbiguousAgentError,
    Workspace,
    WorkspaceError,
)


def resolve(
    *,
    agent: str | None = None,
    schema: Path | None = None,
    endpoint: str | None = None,
    api_key: str | None = None,
    require_remote: bool = False,
) -> AgentContext:
    """Resolve an :class:`AgentContext` or abort the CLI with a helpful message.

    Flag-level overrides take priority over workspace-derived values so that
    scripts / CI can still force an endpoint or API key on a single run
    without editing ``expert.toml``.

    When ``require_remote`` is set, missing ``endpoint`` / ``api_key`` turn
    into a non-zero exit instead of being silently ``None``.
    """
    ws = Workspace.discover()
    try:
        ctx = ws.resolve(selector=agent, schema_override=schema)
    except (AgentNotFoundError, AmbiguousAgentError, WorkspaceError) as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    # Flag overrides from the caller take precedence over anything the
    # workspace resolver produced.
    if endpoint or api_key:
        ctx = replace(
            ctx,
            endpoint=endpoint or ctx.endpoint,
            api_key=api_key or ctx.api_key,
        )

    if require_remote:
        try:
            ctx.require_remote()
        except WorkspaceError as exc:
            print_error(str(exc))
            raise typer.Exit(code=2) from exc

    return ctx


__all__ = ["resolve"]
