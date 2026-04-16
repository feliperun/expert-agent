"""`agent-cli ask` — send a question to an agent and stream the answer.

Uses SSE (Server-Sent Events). The server emits events of types:

- `delta`    — partial answer text. Payload: `{"text": "..."}`.
- `citation` — a retrieved source. Payload: `{"title": "...", "url": "..."}`.
- `done`    — end of stream, with usage summary. Payload:
              `{"usage": {"input_tokens": int, "output_tokens": int, "cost_usd": float}}`.
- `error`   — server-side error. Payload: `{"message": "..."}`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
import typer
from rich.live import Live
from rich.markdown import Markdown

from ..config import make_http_client
from ..ui import console, print_error, print_info, print_success

_USER_ID = "cli"


async def _stream_ask(
    *,
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    stream: bool,
) -> int:
    async with make_http_client(endpoint=endpoint, api_key=api_key) as client:
        if not stream:
            return await _oneshot(client, payload)
        return await _live_stream(client, payload)


async def _oneshot(client: httpx.AsyncClient, payload: dict[str, Any]) -> int:
    response = await client.post("/ask", json={**payload, "stream": False})
    response.raise_for_status()
    body = response.json()
    text = str(body.get("answer", ""))
    console.print(Markdown(text))
    citations = body.get("citations") or []
    if citations:
        _print_citations(citations)
    usage = body.get("usage")
    if isinstance(usage, dict):
        _print_usage(usage)
    return 0


async def _live_stream(client: httpx.AsyncClient, payload: dict[str, Any]) -> int:
    answer: list[str] = []
    citations: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None

    async with (
        client.stream(
            "POST",
            "/ask",
            json={**payload, "stream": True},
            headers={"Accept": "text/event-stream"},
        ) as response,
    ):
        response.raise_for_status()
        with Live(Markdown(""), console=console, refresh_per_second=12, vertical_overflow="visible") as live:
            async for event_type, data in _iter_sse(response):
                if event_type == "delta":
                    text = str(data.get("text", ""))
                    if text:
                        answer.append(text)
                        live.update(Markdown("".join(answer)))
                elif event_type == "citation":
                    citations.append(data)
                elif event_type == "done":
                    u = data.get("usage")
                    if isinstance(u, dict):
                        usage = u
                    break
                elif event_type == "error":
                    message = str(data.get("message", "unknown error"))
                    raise _ServerError(message)

    if citations:
        _print_citations(citations)
    if usage is not None:
        _print_usage(usage)
    return 0


async def _iter_sse(
    response: httpx.Response,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield `(event, data_dict)` tuples from an SSE response."""
    event: str = "message"
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        if raw_line == "":
            if data_lines:
                data_str = "\n".join(data_lines)
                parsed: dict[str, Any]
                try:
                    loaded = json.loads(data_str)
                    parsed = loaded if isinstance(loaded, dict) else {"value": loaded}
                except json.JSONDecodeError:
                    parsed = {"text": data_str}
                yield event, parsed
            event = "message"
            data_lines = []
            continue
        if raw_line.startswith(":"):
            continue
        if raw_line.startswith("event:"):
            event = raw_line[6:].strip() or "message"
        elif raw_line.startswith("data:"):
            data_lines.append(raw_line[5:].lstrip())


def _print_citations(citations: list[dict[str, Any]]) -> None:
    console.print()
    console.print("[bold]Sources[/bold]")
    for idx, citation in enumerate(citations, start=1):
        title = citation.get("title") or citation.get("path") or "source"
        url = citation.get("url") or citation.get("path") or ""
        console.print(f"  [{idx}] [cyan]{title}[/cyan] [dim]{url}[/dim]")


def _print_usage(usage: dict[str, Any]) -> None:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cost = usage.get("cost_usd")
    parts: list[str] = []
    if input_tokens is not None:
        parts.append(f"in={input_tokens:,}")
    if output_tokens is not None:
        parts.append(f"out={output_tokens:,}")
    if cost is not None:
        parts.append(f"cost=${float(cost):.4f}")
    if parts:
        console.print()
        print_info("Usage: " + " | ".join(parts))


class _ServerError(RuntimeError):
    pass


def cmd(
    question: Annotated[str, typer.Argument(help="Question to send to the agent.")],
    endpoint: Annotated[
        str,
        typer.Option(
            "--endpoint",
            envvar="EXPERT_AGENT_ENDPOINT",
            help="Base URL of the running agent.",
        ),
    ],
    api_key: Annotated[
        str,
        typer.Option(
            "--api-key",
            envvar="EXPERT_AGENT_API_KEY",
            help="Admin bearer token.",
        ),
    ],
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            help="Session ID to continue. If omitted, a new UUID is generated.",
        ),
    ] = None,
    stream: Annotated[
        bool,
        typer.Option(
            "--stream/--no-stream",
            help="Stream the answer via SSE (default) or wait for the complete response.",
        ),
    ] = True,
) -> None:
    """Ask the agent a question."""
    if session is None:
        session = str(uuid.uuid4())
        print_info(f"Starting new session [cyan]{session}[/cyan].")

    payload = {
        "user_id": _USER_ID,
        "session_id": session,
        "message": question,
    }

    try:
        exit_code = asyncio.run(
            _stream_ask(
                endpoint=endpoint.rstrip("/"),
                api_key=api_key,
                payload=payload,
                stream=stream,
            )
        )
    except _ServerError as exc:
        print_error(f"server error: {exc}")
        raise typer.Exit(code=2) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            print_error(f"authentication failed ({status}): check EXPERT_AGENT_API_KEY.")
            raise typer.Exit(code=3) from exc
        print_error(f"server returned {status}.")
        raise typer.Exit(code=2) from exc
    except httpx.ConnectError as exc:
        print_error(
            f"could not connect to {endpoint}. Is the agent running and reachable?"
        )
        raise typer.Exit(code=2) from exc
    except httpx.HTTPError as exc:
        print_error(f"network error: {exc}")
        raise typer.Exit(code=2) from exc

    if exit_code == 0 and not stream:
        print_success("Response complete.")
    # TODO(expert-agent): surface a hint when no answer text was produced.
