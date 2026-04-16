"""`agent-cli sessions` — list/show/delete user sessions (LGPD support)."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import httpx
import typer
from rich.markdown import Markdown
from rich.table import Table

from ..config import make_http_client
from ..ui import console, print_error, print_info, print_success, print_warning

app = typer.Typer(
    name="sessions",
    help="Manage user sessions (list, show, delete — for LGPD right-to-erasure).",
    no_args_is_help=True,
)


async def _get_json(
    endpoint: str, api_key: str, path: str
) -> Any:
    async with make_http_client(endpoint=endpoint, api_key=api_key) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.json()


async def _delete(endpoint: str, api_key: str, path: str) -> None:
    async with make_http_client(endpoint=endpoint, api_key=api_key) as client:
        response = await client.delete(path)
        response.raise_for_status()


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            print_error(f"authentication failed ({status}): check EXPERT_AGENT_API_KEY.")
            raise typer.Exit(code=3) from exc
        if status == 404:
            print_error("not found.")
            raise typer.Exit(code=1) from exc
        print_error(f"server returned {status}.")
        raise typer.Exit(code=2) from exc
    except httpx.HTTPError as exc:
        print_error(f"network error: {exc}")
        raise typer.Exit(code=2) from exc


_EndpointOpt = Annotated[
    str,
    typer.Option(
        "--endpoint", envvar="EXPERT_AGENT_ENDPOINT", help="Base URL of the agent."
    ),
]
_ApiKeyOpt = Annotated[
    str,
    typer.Option(
        "--api-key", envvar="EXPERT_AGENT_API_KEY", help="Admin bearer token."
    ),
]


@app.command("list")
def list_cmd(
    endpoint: _EndpointOpt,
    api_key: _ApiKeyOpt,
    user: Annotated[
        str | None,
        typer.Option("--user", help="Filter sessions by user_id."),
    ] = None,
) -> None:
    """List active sessions."""
    path = "/sessions"
    if user:
        path = f"/sessions?user_id={user}"
    body = _run(_get_json(endpoint.rstrip("/"), api_key, path))
    items: list[dict[str, Any]]
    if isinstance(body, list):
        items = [x for x in body if isinstance(x, dict)]
    elif isinstance(body, dict) and isinstance(body.get("sessions"), list):
        items = [x for x in body["sessions"] if isinstance(x, dict)]
    else:
        items = []

    if not items:
        print_warning("No sessions found.")
        return

    table = Table(title="Sessions")
    table.add_column("ID", overflow="fold")
    table.add_column("User", overflow="fold")
    table.add_column("Messages", justify="right")
    table.add_column("Updated at")
    for item in items:
        table.add_row(
            str(item.get("id") or item.get("session_id") or ""),
            str(item.get("user_id") or ""),
            str(item.get("message_count") or item.get("messages") or ""),
            str(item.get("updated_at") or ""),
        )
    console.print(table)


@app.command("show")
def show_cmd(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    endpoint: _EndpointOpt,
    api_key: _ApiKeyOpt,
) -> None:
    """Show the message history of a single session."""
    body = _run(_get_json(endpoint.rstrip("/"), api_key, f"/sessions/{session_id}"))
    if not isinstance(body, dict):
        print_error("unexpected response shape.")
        raise typer.Exit(code=2)

    messages_raw = body.get("messages") or body.get("history") or []
    messages: list[dict[str, Any]] = [m for m in messages_raw if isinstance(m, dict)]
    print_info(
        f"Session [cyan]{session_id}[/cyan] — user=[cyan]{body.get('user_id', '')}[/cyan] "
        f"messages={len(messages)}"
    )
    for idx, msg in enumerate(messages, start=1):
        role = str(msg.get("role", "unknown"))
        content = str(msg.get("content", ""))
        header = f"[bold]#{idx} {role}[/bold]"
        console.print(header)
        console.print(Markdown(content))
        console.print()


@app.command("delete")
def delete_cmd(
    session_id: Annotated[str, typer.Argument(help="Session ID to delete.")],
    endpoint: _EndpointOpt,
    api_key: _ApiKeyOpt,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Delete a session and its message history (LGPD right-to-erasure)."""
    if not yes:
        confirmed = typer.confirm(
            f"Delete session {session_id}? This action is irreversible.",
            default=False,
        )
        if not confirmed:
            print_warning("Aborted.")
            raise typer.Exit(code=0)

    _run(_delete(endpoint.rstrip("/"), api_key, f"/sessions/{session_id}"))
    print_success(f"Session [cyan]{session_id}[/cyan] deleted.")
