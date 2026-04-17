"""`agent-cli ask` — send a question to an agent and stream the answer.

Streaming UX:

1. **Snake phase** (time-to-first-token) — an animated gradient "snake"
   label traces the top of the Live while the server warms up / thinks.
2. **Typewriter phase** (first token → done) — tokens land in an in-memory
   queue; a painter coroutine drains it char-by-char at an adaptive rate,
   so Gemini's chunky ~200-char batches still feel like a fluid stream.
3. **Final frame** — replace the plain-text buffer with a nicely rendered
   Markdown block, then print citations and token usage below.

Server contract (see `backend/app/routes/ask.py`):

- `token`    — `{"text": "...", "request_id": "..."}`.
- `citation` — `{"source_uri": "...", "start_index": int, "end_index": int,
                 "snippet": "..."}`.
- `done`     — `{"finish_reason": "...",
                 "usage": {"input_tokens": int, "output_tokens": int,
                           "cached_tokens": int},
                 "citations": [...]}`.
- `error`    — `{"detail": "..."}`.

Non-streaming JSON (`--no-stream`) uses `AskSyncResponse`:
`{"text": "...", "citations": [...], "usage": {...}, "request_id": "..."}`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated, Any

import httpx
import typer
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from ..config import make_http_client
from ..ui import console, print_error, print_info, print_success

_USER_ID = "cli"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Non-streaming (`--no-stream`)
# ---------------------------------------------------------------------------


async def _oneshot(client: httpx.AsyncClient, payload: dict[str, Any]) -> int:
    response = await client.post("/ask", json={**payload, "stream": False})
    response.raise_for_status()
    body = response.json()
    text = str(body.get("text", ""))
    if text:
        console.print(Markdown(text))
    citations = body.get("citations") or []
    if citations:
        _print_citations(citations)
    usage = body.get("usage")
    if isinstance(usage, dict):
        _print_usage(usage)
    if not text:
        print_info("Server returned an empty answer.")
    return 0


# ---------------------------------------------------------------------------
# Streaming — snake animation + adaptive typewriter
# ---------------------------------------------------------------------------


@dataclass
class _Stream:
    chars: deque[str] = field(default_factory=deque)
    painted: list[str] = field(default_factory=list)
    server_done: bool = False
    first_token_at: float | None = None
    started_at: float = field(default_factory=time.perf_counter)


# Visual tuning. Numbers picked after eyeballing on a 120x40 terminal; they
# balance "feels alive while waiting" against "doesn't lag behind a fast
# Gemini burst". The adaptive batch/delay schedule is monotone in queue
# depth so there are no pathological feedback loops.
_SNAKE_WIDTH = 16
_SNAKE_TRAIL = 5
_HEAD_GRADIENT: tuple[str, ...] = (
    "bright_cyan",
    "cyan",
    "blue",
    "magenta",
    "bright_magenta",
)
_SNAKE_REST_CHAR = "▱"
_SNAKE_HEAD_CHAR = "▰"
_SNAKE_FRAME_SECONDS = 0.07


def _snake_frame(tick: int, status: str = "Thinking") -> Text:
    """Render one frame of the rolling gradient snake."""
    text = Text()
    text.append(" ", style="")
    text.append(f"{status} ", style="bold white")
    head = tick % _SNAKE_WIDTH
    for i in range(_SNAKE_WIDTH):
        offset = (head - i) % _SNAKE_WIDTH
        if offset < _SNAKE_TRAIL:
            style = (
                _HEAD_GRADIENT[offset]
                if offset < len(_HEAD_GRADIENT)
                else _HEAD_GRADIENT[-1]
            )
            text.append(_SNAKE_HEAD_CHAR, style=style)
        else:
            text.append(_SNAKE_REST_CHAR, style="grey30")
    return text


def _typing_frame(painted: str, *, cursor: bool) -> Text:
    text = Text(painted, style="white", overflow="fold")
    if cursor:
        text.append("▍", style="bold cyan blink")
    return text


async def _painter(live: Live, stream: _Stream) -> None:
    """Drive the Live renderable: snake → typewriter → final plain-text."""
    tick = 0
    # Phase 1: snake while waiting for the first byte.
    while stream.first_token_at is None and not stream.server_done:
        live.update(_snake_frame(tick))
        tick += 1
        try:
            await asyncio.sleep(_SNAKE_FRAME_SECONDS)
        except asyncio.CancelledError:
            return

    # Phase 2: typewriter. Burn through the queue at an adaptive rate so
    # large bursts from Gemini (~200 chars/chunk) don't puddle up.
    while True:
        queue_len = len(stream.chars)
        if queue_len:
            if queue_len > 400:
                batch, delay = 8, 0.004
            elif queue_len > 120:
                batch, delay = 4, 0.006
            elif queue_len > 40:
                batch, delay = 2, 0.010
            else:
                batch, delay = 1, 0.018
            for _ in range(batch):
                if not stream.chars:
                    break
                stream.painted.append(stream.chars.popleft())
            live.update(_typing_frame("".join(stream.painted), cursor=True))
        elif stream.server_done:
            break
        else:
            delay = 0.02

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

    # Hide the cursor on the very last frame before the Markdown swap.
    live.update(_typing_frame("".join(stream.painted), cursor=False))


async def _receive(
    response: httpx.Response,
    stream: _Stream,
    citations: list[dict[str, Any]],
    usage_slot: dict[str, Any],
) -> None:
    """Consume the SSE events and feed the `_Stream` buffer."""
    async for event_type, data in _iter_sse(response):
        if event_type == "token":
            text = str(data.get("text", ""))
            if not text:
                continue
            if stream.first_token_at is None:
                stream.first_token_at = time.perf_counter()
            stream.chars.extend(text)
        elif event_type == "citation":
            citations.append(data)
        elif event_type == "done":
            usage = data.get("usage")
            if isinstance(usage, dict):
                usage_slot["value"] = usage
            trailing = data.get("citations")
            if isinstance(trailing, list) and not citations:
                citations.extend(trailing)
            stream.server_done = True
            return
        elif event_type == "error":
            stream.server_done = True
            message = str(data.get("detail") or data.get("message") or "unknown error")
            raise _ServerError(message)


async def _live_stream(client: httpx.AsyncClient, payload: dict[str, Any]) -> int:
    stream = _Stream()
    citations: list[dict[str, Any]] = []
    usage_slot: dict[str, Any] = {}

    async with client.stream(
        "POST",
        "/ask",
        json={**payload, "stream": True},
        headers={"Accept": "text/event-stream"},
    ) as response:
        response.raise_for_status()
        with Live(
            _snake_frame(0),
            console=console,
            refresh_per_second=30,
            vertical_overflow="visible",
        ) as live:
            painter_task = asyncio.create_task(_painter(live, stream))
            try:
                await _receive(response, stream, citations, usage_slot)
            finally:
                # Unblock the painter: drain remaining chars and exit.
                stream.server_done = True
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await painter_task

            final_text = "".join(stream.painted)
            if final_text:
                live.update(Markdown(final_text))

    if citations:
        _print_citations(citations)
    usage = usage_slot.get("value")
    if isinstance(usage, dict):
        _print_usage(usage)
    if stream.first_token_at is not None:
        ttft = stream.first_token_at - stream.started_at
        total = time.perf_counter() - stream.started_at
        print_info(f"TTFT {ttft:.1f}s | total {total:.1f}s")
    if not stream.painted:
        print_info("Server returned an empty answer.")
    return 0


# ---------------------------------------------------------------------------
# SSE parser + terminal widgets
# ---------------------------------------------------------------------------


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
        source = (
            citation.get("source_uri")
            or citation.get("url")
            or citation.get("path")
            or citation.get("title")
            or "source"
        )
        snippet = citation.get("snippet") or ""
        if snippet:
            snippet_line = snippet if len(snippet) <= 120 else snippet[:117] + "..."
            console.print(f"  [{idx}] [cyan]{source}[/cyan]")
            console.print(f"      [dim]{snippet_line}[/dim]")
        else:
            console.print(f"  [{idx}] [cyan]{source}[/cyan]")


def _print_usage(usage: dict[str, Any]) -> None:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cached_tokens = usage.get("cached_tokens")
    cost = usage.get("cost_usd")
    parts: list[str] = []
    if input_tokens is not None:
        parts.append(f"in={input_tokens:,}")
    if output_tokens is not None:
        parts.append(f"out={output_tokens:,}")
    if cached_tokens:
        parts.append(f"cached={cached_tokens:,}")
    if cost is not None:
        parts.append(f"cost=${float(cost):.4f}")
    if parts:
        console.print()
        print_info("Usage: " + " | ".join(parts))


class _ServerError(RuntimeError):
    pass
