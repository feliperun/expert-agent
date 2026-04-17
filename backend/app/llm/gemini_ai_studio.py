"""`google-genai` implementation of `LLMClient` against the AI Studio endpoint.

The SDK surface (caches, streaming, count_tokens) is the same between AI
Studio and Vertex; only the client construction differs. This class targets
the AI Studio flavour (API-key auth) which is what `spec.model.provider ==
"gemini"` means in the agent schema.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import structlog
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .protocol import (
    CacheNotFoundError,
    CacheRef,
    Citation,
    Content,
    FileRef,
    GenerationChunk,
    Usage,
)

logger = structlog.get_logger(__name__)

# Conservative default for unit tests / smoke runs. Production agents pin a
# real Pro tier (e.g. ``gemini-2.5-pro``) via ``spec.model.name`` in their
# AgentSchema; bump together with the SDK version when a newer Pro ships.
DEFAULT_MODEL = "gemini-2.0-flash-exp"

_TRANSIENT_EXC: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)


def _build_retry() -> AsyncRetrying:
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
        retry=retry_if_exception_type(_TRANSIENT_EXC),
    )


def _is_cache_not_found(exc: BaseException) -> bool:
    """Best-effort detection of the Gemini 'cache expired/missing' error.

    The SDK wraps the HTTP error in `google.genai.errors.APIError`, but we do
    not import it at module scope to keep the module importable in unit tests
    without the SDK installed. Detection is by (a) HTTP 404 / NOT_FOUND status
    strings and (b) `CachedContent` keyword in the message.
    """
    msg = str(exc).lower()
    if "not_found" in msg or "404" in msg:
        return "cache" in msg or "cachedcontent" in msg
    return False


class GeminiAIStudioClient:
    """Async adapter over `google.genai.Client`.

    Parameters
    ----------
    api_key:
        Gemini AI Studio API key (secret).
    model:
        Model identifier, e.g. ``"gemini-2.5-pro"`` or
        ``"gemini-2.0-flash-exp"`` for cheaper smoke tests.
    max_citations:
        Upper bound on citations surfaced per generation chunk.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_citations: int = 10,
        thinking_budget: int | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("GeminiAIStudioClient requires a non-empty api_key")
        self._model = model
        self._max_citations = max_citations
        self._thinking_budget = thinking_budget
        self._client: Any = self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str) -> Any:
        from google import genai

        return genai.Client(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    async def create_cache(
        self,
        docs: list[FileRef],
        system_instruction: str,
        ttl_seconds: int,
    ) -> CacheRef:
        from google.genai import types as gt

        parts = [await self._part_from_doc(doc) for doc in docs]
        config = gt.CreateCachedContentConfig(
            contents=[gt.Content(role="user", parts=parts)] if parts else [],
            system_instruction=system_instruction,
            ttl=f"{ttl_seconds}s",
        )

        cached: Any
        async for attempt in _build_retry():
            with attempt:
                cached = await self._client.aio.caches.create(
                    model=self._model,
                    config=config,
                )

        expire_time = _coerce_datetime(getattr(cached, "expire_time", None), ttl_seconds)
        logger.info(
            "llm.cache.created",
            cache_name=cached.name,
            model=self._model,
            ttl_seconds=ttl_seconds,
            file_count=len(docs),
        )
        return CacheRef(name=cached.name, expire_time=expire_time, model=self._model)

    async def _part_from_doc(self, doc: FileRef) -> Any:
        """Build a `types.Part` for a single doc.

        The Gemini AI Studio (`v1beta`) caches API does NOT accept `gs://`
        URIs — only File API URIs. For Vertex you can pass `gs://` directly,
        but here we transparently mirror GCS bytes into the File API on demand.
        Result: the cache is built from File API uploads while GCS remains the
        durable source of truth (so re-syncs are cheap and the agent stays
        portable across LLM providers).
        """
        from google.genai import types as gt

        if not doc.gcs_uri.startswith("gs://"):
            return gt.Part.from_uri(file_uri=doc.gcs_uri, mime_type=doc.mime_type)

        file_uri = await self._mirror_gcs_to_file_api(doc)
        return gt.Part.from_uri(file_uri=file_uri, mime_type=doc.mime_type)

    async def _mirror_gcs_to_file_api(self, doc: FileRef) -> str:
        """Download a GCS object once, upload it to the File API, return its URI.

        File API uploads survive ~48h, so we don't bother caching the URI: each
        cache rebuild re-uploads, which is fine because the rebuild itself is
        rare (TTL ≥ 1h) and File API ingestion is cheap and parallel.
        """
        import asyncio
        import io
        from urllib.parse import urlparse

        parsed = urlparse(doc.gcs_uri)
        bucket_name, object_key = parsed.netloc, parsed.path.lstrip("/")

        def _download() -> bytes:
            # `google.cloud` is a namespace package, so mypy can't resolve the
            # `storage` attribute statically even though the distribution
            # `google-cloud-storage` is installed.
            from google.cloud import storage  # type: ignore[attr-defined]

            client = storage.Client()
            blob = client.bucket(bucket_name).blob(object_key)
            data: bytes = blob.download_as_bytes()
            return data

        data = await asyncio.to_thread(_download)
        buffer = io.BytesIO(data)
        display_name = object_key.rsplit("/", 1)[-1]

        from google.genai import types as gt

        uploaded = await self._client.aio.files.upload(
            file=buffer,
            config=gt.UploadFileConfig(
                mime_type=doc.mime_type,
                display_name=display_name,
            ),
        )
        return str(uploaded.uri)

    async def update_cache_ttl(self, cache: CacheRef, ttl_seconds: int) -> None:
        from google.genai import types as gt

        config = gt.UpdateCachedContentConfig(ttl=f"{ttl_seconds}s")
        async for attempt in _build_retry():
            with attempt:
                await self._client.aio.caches.update(name=cache.name, config=config)
        logger.info("llm.cache.ttl_updated", cache_name=cache.name, ttl_seconds=ttl_seconds)

    async def delete_cache(self, cache: CacheRef) -> None:
        try:
            async for attempt in _build_retry():
                with attempt:
                    await self._client.aio.caches.delete(name=cache.name)
        except RetryError as exc:  # pragma: no cover - defensive
            logger.warning("llm.cache.delete_failed", cache_name=cache.name, error=str(exc))
            return
        logger.info("llm.cache.deleted", cache_name=cache.name)

    async def count_tokens(self, text: str) -> int:
        from google.genai import types as gt

        async for attempt in _build_retry():
            with attempt:
                response = await self._client.aio.models.count_tokens(
                    model=self._model,
                    contents=[gt.Content(role="user", parts=[gt.Part(text=text)])],
                )
        return int(response.total_tokens)

    async def close(self) -> None:
        # The SDK does not currently expose an async close hook; we just drop
        # the client reference so GC can clean up the underlying httpx client.
        self._client = None

    def generate_stream(
        self,
        cache: CacheRef,
        contents: list[Content],
        *,
        grounding: bool = True,
    ) -> AsyncIterator[GenerationChunk]:
        return self._iterate_stream(cache=cache, contents=contents, grounding=grounding)

    async def _iterate_stream(
        self,
        *,
        cache: CacheRef,
        contents: list[Content],
        grounding: bool,
    ) -> AsyncIterator[GenerationChunk]:
        from google.genai import types as gt

        sdk_contents = [_to_sdk_content(c) for c in contents]
        tools = [gt.Tool(google_search=gt.GoogleSearch())] if grounding else None
        thinking_config = (
            gt.ThinkingConfig(thinking_budget=self._thinking_budget)
            if self._thinking_budget is not None
            else None
        )
        config = gt.GenerateContentConfig(
            cached_content=cache.name,
            tools=tools,
            thinking_config=thinking_config,
        )

        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=cache.model or self._model,
                contents=sdk_contents,
                config=config,
            )
        except Exception as exc:
            if _is_cache_not_found(exc):
                raise CacheNotFoundError(str(exc)) from exc
            raise

        try:
            async for raw_chunk in stream:
                yield self._map_chunk(raw_chunk)
        except Exception as exc:
            if _is_cache_not_found(exc):
                raise CacheNotFoundError(str(exc)) from exc
            raise

    def _map_chunk(self, raw: Any) -> GenerationChunk:
        text = getattr(raw, "text", "") or ""
        finish_reason: str | None = None
        citations: list[Citation] = []

        candidates = getattr(raw, "candidates", None) or []
        if candidates:
            cand = candidates[0]
            fr = getattr(cand, "finish_reason", None)
            if fr is not None:
                finish_reason = _enum_name(fr)
            grounding = getattr(cand, "grounding_metadata", None)
            if grounding is not None:
                citations = self._extract_citations(grounding)[: self._max_citations]

        usage = _map_usage(getattr(raw, "usage_metadata", None))
        return GenerationChunk(
            text=text,
            finish_reason=finish_reason,
            citations=citations,
            usage=usage,
        )

    @staticmethod
    def _extract_citations(grounding_metadata: Any) -> list[Citation]:
        chunks = getattr(grounding_metadata, "grounding_chunks", None) or []
        supports = getattr(grounding_metadata, "grounding_supports", None) or []
        citations: list[Citation] = []
        for support in supports:
            segment = getattr(support, "segment", None)
            if segment is None:
                continue
            indices = getattr(support, "grounding_chunk_indices", None) or []
            start = int(getattr(segment, "start_index", 0) or 0)
            end = int(getattr(segment, "end_index", 0) or 0)
            snippet = str(getattr(segment, "text", "") or "")
            for idx in indices:
                if idx < 0 or idx >= len(chunks):
                    continue
                chunk = chunks[idx]
                web = getattr(chunk, "web", None)
                retrieved = getattr(chunk, "retrieved_context", None)
                source_uri = getattr(web, "uri", None) or getattr(retrieved, "uri", None) or ""
                citations.append(
                    Citation(
                        source_uri=str(source_uri),
                        start_index=start,
                        end_index=end,
                        snippet=snippet,
                    )
                )
        return citations


def _to_sdk_content(content: Content) -> Any:
    from google.genai import types as gt

    parts = [gt.Part(text=p.text or "") for p in content.parts]
    return gt.Content(role=content.role, parts=parts)


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def _map_usage(usage: Any) -> Usage | None:
    if usage is None:
        return None
    return Usage(
        input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
        output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        cached_tokens=int(getattr(usage, "cached_content_token_count", 0) or 0),
    )


def _coerce_datetime(value: Any, ttl_seconds: int) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.now(tz=UTC)
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:  # pragma: no cover - defensive
        return datetime.now(tz=UTC)


__all__ = ["DEFAULT_MODEL", "GeminiAIStudioClient"]
