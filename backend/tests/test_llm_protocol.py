"""Tests for the LLMClient contract and GeminiAIStudioClient adapter.

We don't exercise the real `google-genai` network layer — instead the SDK's
async client is replaced with an in-memory fake so we can assert that
`GeminiAIStudioClient` wires arguments correctly and maps SDK responses to
`GenerationChunk`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.llm.gemini_ai_studio import GeminiAIStudioClient
from app.llm.protocol import (
    CacheNotFoundError,
    CacheRef,
    Content,
    ContentPart,
    FileRef,
    LLMClient,
)


@dataclass
class _FakeCached:
    name: str
    expire_time: datetime = field(default_factory=lambda: datetime.now(tz=UTC) + timedelta(hours=1))


class _FakeAsyncCaches:
    def __init__(self) -> None:
        self.created: list[tuple[str, Any]] = []
        self.updated: list[tuple[str, Any]] = []
        self.deleted: list[str] = []

    async def create(self, *, model: str, config: Any) -> _FakeCached:
        self.created.append((model, config))
        return _FakeCached(name="cachedContents/abc123")

    async def update(self, *, name: str, config: Any) -> None:
        self.updated.append((name, config))

    async def delete(self, *, name: str) -> None:
        self.deleted.append(name)


class _FakeAsyncModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chunks: list[Any] = []
        self.total_tokens = 42
        self.raise_on_call: BaseException | None = None
        self.raise_on_iter: BaseException | None = None

    async def count_tokens(self, *, model: str, contents: Any) -> Any:
        @dataclass
        class _CountResult:
            total_tokens: int

        return _CountResult(total_tokens=self.total_tokens)

    async def generate_content_stream(
        self, *, model: str, contents: Any, config: Any
    ) -> AsyncIterator[Any]:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.raise_on_call is not None:
            raise self.raise_on_call

        chunks = self.chunks

        async def _iter() -> AsyncIterator[Any]:
            for chunk in chunks:
                yield chunk
            if self.raise_on_iter is not None:
                raise self.raise_on_iter

        return _iter()


class _FakeAio:
    def __init__(self) -> None:
        self.caches = _FakeAsyncCaches()
        self.models = _FakeAsyncModels()


class _FakeClient:
    def __init__(self) -> None:
        self.aio = _FakeAio()


def _make_client(*, thinking_budget: int | None = None) -> tuple[GeminiAIStudioClient, _FakeClient]:
    fake = _FakeClient()
    client = GeminiAIStudioClient.__new__(GeminiAIStudioClient)
    # Manual init to avoid importing google.genai in tests.
    client._model = "gemini-test"  # type: ignore[attr-defined]
    client._max_citations = 10  # type: ignore[attr-defined]
    client._thinking_budget = thinking_budget  # type: ignore[attr-defined]
    client._client = fake  # type: ignore[attr-defined]
    return client, fake


def test_fake_llm_satisfies_protocol() -> None:
    # Runtime structural check — the fake in conftest implements LLMClient.
    from tests.conftest import FakeLLM

    instance = FakeLLM()
    assert isinstance(instance, LLMClient)


@pytest.mark.asyncio
async def test_create_cache_builds_config_from_files() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client()

    docs = [
        FileRef(gcs_uri="gs://bucket/a.pdf", mime_type="application/pdf"),
        FileRef(gcs_uri="gs://bucket/b.md", mime_type="text/markdown"),
    ]
    cache = await client.create_cache(
        docs=docs, system_instruction="You are an expert.", ttl_seconds=1800
    )

    assert cache.name == "cachedContents/abc123"
    assert cache.model == "gemini-test"
    assert len(fake.aio.caches.created) == 1
    model_used, cfg = fake.aio.caches.created[0]
    assert model_used == "gemini-test"
    assert cfg.ttl == "1800s"
    assert cfg.system_instruction == "You are an expert."
    assert len(cfg.contents) == 1


@pytest.mark.asyncio
async def test_update_and_delete_cache() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client()
    cache = CacheRef(
        name="cachedContents/xyz",
        expire_time=datetime.now(tz=UTC),
        model="gemini-test",
    )
    await client.update_cache_ttl(cache, 600)
    await client.delete_cache(cache)

    assert fake.aio.caches.updated[0][0] == "cachedContents/xyz"
    assert fake.aio.caches.updated[0][1].ttl == "600s"
    assert fake.aio.caches.deleted == ["cachedContents/xyz"]


@pytest.mark.asyncio
async def test_count_tokens() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client()
    fake.aio.models.total_tokens = 120

    result = await client.count_tokens("hello world")
    assert result == 120


@pytest.mark.asyncio
async def test_generate_stream_yields_chunks() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client()

    @dataclass
    class _Usage:
        prompt_token_count: int = 10
        candidates_token_count: int = 3
        cached_content_token_count: int = 8

    @dataclass
    class _Candidate:
        finish_reason: str = "STOP"
        grounding_metadata: Any = None

    @dataclass
    class _Chunk:
        text: str
        candidates: list[_Candidate] = field(default_factory=lambda: [_Candidate(finish_reason="")])
        usage_metadata: _Usage | None = None

    fake.aio.models.chunks = [
        _Chunk(text="Hello"),
        _Chunk(text=" world", usage_metadata=_Usage()),
        _Chunk(text="!", candidates=[_Candidate(finish_reason="STOP")]),
    ]

    cache = CacheRef(
        name="cachedContents/xyz",
        expire_time=datetime.now(tz=UTC),
        model="gemini-test",
    )
    contents = [Content(role="user", parts=[ContentPart(text="hi")])]

    texts: list[str] = []
    finish: list[str | None] = []
    usages = []
    async for chunk in client.generate_stream(cache, contents, grounding=False):
        texts.append(chunk.text)
        finish.append(chunk.finish_reason)
        if chunk.usage is not None:
            usages.append(chunk.usage)

    assert texts == ["Hello", " world", "!"]
    assert "STOP" in finish
    assert usages and usages[0].input_tokens == 10 and usages[0].cached_tokens == 8
    assert len(fake.aio.models.calls) == 1
    assert fake.aio.models.calls[0]["config"].cached_content == "cachedContents/xyz"
    # No thinking_budget configured → SDK default (no ThinkingConfig sent).
    assert fake.aio.models.calls[0]["config"].thinking_config is None


@pytest.mark.asyncio
async def test_generate_stream_forwards_thinking_budget() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client(thinking_budget=128)

    @dataclass
    class _Chunk:
        text: str
        candidates: list[Any] = field(default_factory=list)
        usage_metadata: Any = None

    fake.aio.models.chunks = [_Chunk(text="ok")]

    cache = CacheRef(
        name="cachedContents/xyz",
        expire_time=datetime.now(tz=UTC),
        model="gemini-test",
    )
    async for _ in client.generate_stream(
        cache, [Content(role="user", parts=[ContentPart(text="hi")])], grounding=False
    ):
        pass

    cfg = fake.aio.models.calls[0]["config"]
    # ThinkingConfig exposes the budget under `thinking_budget` (snake_case)
    # on the pydantic model even though the SDK kwarg is camelCase.
    assert cfg.thinking_config is not None
    assert cfg.thinking_config.thinking_budget == 128


@pytest.mark.asyncio
async def test_generate_stream_raises_cache_not_found() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client()
    fake.aio.models.raise_on_call = RuntimeError("404 NOT_FOUND CachedContent not found")

    cache = CacheRef(
        name="cachedContents/xyz",
        expire_time=datetime.now(tz=UTC),
        model="gemini-test",
    )
    with pytest.raises(CacheNotFoundError):
        async for _ in client.generate_stream(
            cache, [Content(role="user", parts=[ContentPart(text="hi")])], grounding=False
        ):
            pass


@pytest.mark.asyncio
async def test_generate_stream_cache_not_found_during_iteration() -> None:
    pytest.importorskip("google.genai")
    client, fake = _make_client()

    @dataclass
    class _Chunk:
        text: str
        candidates: list[Any] = field(default_factory=list)
        usage_metadata: Any = None

    fake.aio.models.chunks = [_Chunk(text="hi")]
    fake.aio.models.raise_on_iter = RuntimeError("cached_content 404 not_found")

    cache = CacheRef(
        name="cachedContents/xyz",
        expire_time=datetime.now(tz=UTC),
        model="gemini-test",
    )
    with pytest.raises(CacheNotFoundError):
        async for _ in client.generate_stream(
            cache, [Content(role="user", parts=[ContentPart(text="hi")])], grounding=False
        ):
            pass
