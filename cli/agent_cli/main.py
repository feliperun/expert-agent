"""Top-level `typer` app for `agent-cli`."""

from __future__ import annotations

from typing import Annotated

import typer

from . import __version__
from .commands import ask, count_tokens, init, sessions, sync, validate
from .ui import console

app = typer.Typer(
    name="agent-cli",
    help="CLI for the **expert-agent** framework — scaffold, validate, sync, ask.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
    add_completion=True,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"agent-cli {__version__}")
        raise typer.Exit(code=0)


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


app.command(name="init", help="Scaffold a new agent project.")(init.cmd)
app.command(name="validate", help="Validate an agent_schema.yaml locally.")(validate.cmd)
app.command(
    name="count-tokens",
    help="Estimate total tokens across the knowledge base (for Context Cache sizing).",
)(count_tokens.cmd)
app.command(name="sync", help="Push the local knowledge base to a running agent.")(sync.cmd)
app.command(name="ask", help="Send a question to the agent and stream the answer.")(ask.cmd)
app.add_typer(sessions.app, name="sessions", help="Manage user sessions (LGPD).")


if __name__ == "__main__":
    app()
