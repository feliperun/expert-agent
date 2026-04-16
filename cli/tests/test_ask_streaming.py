"""Tests for `agent-cli ask` with streamed SSE responses."""

from __future__ import annotations

import json

import httpx
import respx
from agent_cli.main import app
from typer.testing import CliRunner


def _sse_body(events: list[tuple[str, dict[str, object]]]) -> bytes:
    """Encode `(event, data_dict)` tuples into an SSE byte stream."""
    chunks: list[str] = []
    for event, data in events:
        chunks.append(f"event: {event}\ndata: {json.dumps(data)}\n\n")
    return "".join(chunks).encode("utf-8")


@respx.mock
def test_ask_streams_deltas_and_renders_final_markdown() -> None:
    body = _sse_body(
        [
            ("delta", {"text": "Hello "}),
            ("delta", {"text": "world!"}),
            ("citation", {"title": "source-a.md", "url": "docs/source-a.md"}),
            (
                "done",
                {"usage": {"input_tokens": 123, "output_tokens": 45, "cost_usd": 0.0012}},
            ),
        ]
    )
    route = respx.post("https://agent.example.com/ask").mock(
        return_value=httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ask",
            "What is up?",
            "--session",
            "s-1",
            "--endpoint",
            "https://agent.example.com",
            "--api-key",
            "secret",
        ],
    )

    assert result.exit_code == 0, result.output
    assert route.called
    assert "Hello world!" in result.output
    assert "source-a.md" in result.output
    assert "in=123" in result.output
    assert "out=45" in result.output


@respx.mock
def test_ask_handles_auth_failure() -> None:
    respx.post("https://agent.example.com/ask").mock(
        return_value=httpx.Response(401, json={"detail": "unauthorized"}),
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ask",
            "hi",
            "--session",
            "s-2",
            "--endpoint",
            "https://agent.example.com",
            "--api-key",
            "bad",
        ],
    )
    assert result.exit_code == 3
    assert "authentication failed" in result.output.lower()


@respx.mock
def test_ask_handles_connection_error() -> None:
    respx.post("https://agent.example.com/ask").mock(
        side_effect=httpx.ConnectError("unreachable"),
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ask",
            "hi",
            "--session",
            "s-3",
            "--endpoint",
            "https://agent.example.com",
            "--api-key",
            "x",
        ],
    )
    assert result.exit_code == 2
    assert "could not connect" in result.output.lower()
