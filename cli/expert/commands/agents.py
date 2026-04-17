"""Workspace-aware agent management commands: ``agents``, ``use``, ``which``.

These are the only commands that *never* need to resolve to a single agent —
they inspect, select, or describe the workspace itself.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from ..ui import console, print_error, print_info, print_success
from ..workspace import (
    AgentNotFoundError,
    AmbiguousAgentError,
    Workspace,
    WorkspaceError,
)


def agents_cmd(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show schema paths and endpoints."),
    ] = False,
) -> None:
    """List every agent known to this workspace."""
    ws = Workspace.discover()
    agents = ws.agents()
    if not agents:
        print_info(
            "No agents found. Scaffold one with `expert init <name>` or create "
            "an `expert.toml` workspace file."
        )
        return

    active = ws.active()
    table = Table(title=f"Agents — workspace: {ws.root}")
    table.add_column("Active", width=6, justify="center")
    table.add_column("Name", style="bold")
    table.add_column("Source", style="dim")
    if verbose:
        table.add_column("Schema")
        table.add_column("Endpoint")
    table.add_column("Description", overflow="fold")

    for info in agents:
        is_active = "✓" if info.name == active else ""
        row = [
            is_active,
            info.name,
            info.source,
        ]
        if verbose:
            try:
                schema_rel = str(info.schema_path.relative_to(ws.root))
            except ValueError:
                schema_rel = str(info.schema_path)
            row.extend([schema_rel, info.endpoint or "—"])
        row.append(info.description or "")
        table.add_row(*row)

    console.print(table)
    if ws.default_agent:
        print_info(f"default (expert.toml): [cyan]{ws.default_agent}[/cyan]")
    if active:
        print_info(f"active (expert use): [cyan]{active}[/cyan]")


def use_cmd(
    name: Annotated[
        str | None,
        typer.Argument(
            help="Agent name to pin as active. Omit to clear the pin.",
        ),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Remove the active-agent pointer."),
    ] = False,
) -> None:
    """Pin an agent as the active one for this workspace (stored locally)."""
    ws = Workspace.discover()

    if clear or (name is None):
        if ws.state_file.is_file():
            ws.clear_active()
            print_success("Cleared active agent pointer.")
        else:
            print_info("No active agent set.")
        return

    try:
        # Re-use matcher so `expert use derm` works when `derm-expert` is declared.
        canonical = ws._match(name)
        ws.set_active(canonical)
    except (AgentNotFoundError, AmbiguousAgentError, WorkspaceError) as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    print_success(f"Active agent set to [cyan]{canonical}[/cyan].")
    print_info(f"State stored in {ws.state_file}")


def which_cmd(
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            "-a",
            help="Preview resolution for the given selector without running anything.",
        ),
    ] = None,
) -> None:
    """Print the agent a bare command (no --agent, no @alias) would resolve to."""
    ws = Workspace.discover()
    try:
        ctx = ws.resolve(selector=agent)
    except (AgentNotFoundError, AmbiguousAgentError, WorkspaceError) as exc:
        print_error(str(exc))
        raise typer.Exit(code=1) from exc

    print_info(f"Active agent: [bold cyan]{ctx.name}[/bold cyan]  (source: {ctx.selector_source})")
    print_info(f"  schema:   {ctx.schema_path}")
    print_info(f"  endpoint: {ctx.endpoint or '—'}")
    print_info(f"  api key:  {'set' if ctx.api_key else '—'}")


__all__ = ["agents_cmd", "use_cmd", "which_cmd"]
