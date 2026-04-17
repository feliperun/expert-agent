"""Top-level `typer` app for `expert`.

The CLI is aware of *multi-agent workspaces*: a repo can host several
`agent_schema.yaml` files and the user can target them individually via:

- Explicit flag: ``expert ask --agent derm "..."``
- Active pointer: ``expert use derm`` then ``expert ask "..."``
- Positional shortcut: ``expert @derm ask "..."``

The ``@alias`` form is handled **here** in the entrypoint via a small
argv rewriter that runs before Typer parses its arguments. The rewriter
turns ``expert @<name> <command> ...`` into
``expert <command> --agent <name> ...`` so downstream commands just need
to accept the standard ``--agent`` flag.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from .brand import render_brand
from .commands import agents as agents_commands
from .commands import ask, count_tokens, init, sessions, sync, test, validate
from .ui import console

app = typer.Typer(
    name="expert",
    help="ground a model on your docs. ship it as an API.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        render_brand(console, include_version=True)
        raise typer.Exit(code=0)


def _brand_cmd() -> None:
    """Print the expert brand block (wordmark + tagline + version)."""
    render_brand(console, include_version=True)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Manage expert-agent projects from the command line."""
    _ = version


# Subcommands that accept `--agent`. Used by the @alias rewriter so that
# nonsense like `expert @derm use my-expert` falls through to a useful error
# instead of silently rewriting into `expert use my-expert --agent derm`.
_AGENT_AWARE: frozenset[str] = frozenset(
    {"ask", "validate", "count-tokens", "sync", "test", "sessions", "which"}
)


def _rewrite_at_alias(argv: list[str]) -> list[str]:
    """Expand a leading ``@<name>`` token into ``--agent <name>`` further right.

    Examples::

        expert @my-expert ask "hi"  → expert ask "hi" --agent my-expert
        expert @derm sessions list  → expert sessions list --agent derm
        expert @my-expert           → expert agents --agent my-expert (listing mode)

    Safe no-ops:

    - ``@`` in argv[1] that isn't the immediate prefix to a known
      agent-aware subcommand is left alone (so ``expert @derm use foo``
      is *not* silently rewritten).
    - Options like ``--foo=@bar`` are never touched because we only look at
      ``argv[1]``.
    """
    if len(argv) < 2 or not argv[1].startswith("@") or len(argv[1]) < 2:
        return argv
    if argv[1] in ("@-", "@"):
        return argv
    alias = argv[1][1:]
    rest = argv[2:]

    subcommand_idx: int | None = None
    for idx, token in enumerate(rest):
        if not token.startswith("-"):
            subcommand_idx = idx
            break
    if subcommand_idx is None or rest[subcommand_idx] not in _AGENT_AWARE:
        # No agent-aware subcommand present: leave argv alone so Typer can
        # render a useful error instead of rewriting into a wrong shape.
        return argv

    # Append `--agent <alias>` at the end so it flows through regardless of
    # whether the subcommand is a leaf (`ask`) or a sub-Typer (`sessions
    # list`). Typer happily routes the flag to the deepest command that
    # declares it.
    return [argv[0], *rest, "--agent", alias]


app.command(name="init", help="Scaffold a new agent project.")(init.cmd)
app.command(name="validate", help="Validate an agent_schema.yaml locally.")(validate.cmd)
app.command(
    name="count-tokens",
    help="Estimate total tokens across the knowledge base (for Context Cache sizing).",
)(count_tokens.cmd)
app.command(name="sync", help="Push the local knowledge base to a running agent.")(sync.cmd)
app.command(name="ask", help="Send a question to the agent and stream the answer.")(ask.cmd)
app.add_typer(sessions.app, name="sessions", help="Manage user sessions (LGPD).")
app.command(
    name="test",
    help="Run the packaged Robot Framework E2E kit against the current agent.",
)(test.cmd)
app.command(
    name="agents",
    help="List agents known to this workspace.",
)(agents_commands.agents_cmd)
app.command(
    name="use",
    help="Pin an agent as the active one for this workspace.",
)(agents_commands.use_cmd)
app.command(
    name="which",
    help="Print which agent a bare command would resolve to.",
)(agents_commands.which_cmd)
app.command(
    name="brand",
    help="Print the expert wordmark + version (fun, mostly).",
    hidden=True,
)(_brand_cmd)


def main() -> None:
    """Entry point that runs the ``@alias`` rewriter before dispatching."""
    sys.argv = _rewrite_at_alias(sys.argv)
    app()


if __name__ == "__main__":
    main()
