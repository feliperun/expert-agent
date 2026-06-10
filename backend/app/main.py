"""FastAPI entrypoint.

`create_app()` builds the application with the current settings/schema so tests
can instantiate it with overrides. `app` is a module-level default used by
`uvicorn app.main:app` in the Dockerfile.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from . import __version__
from .cache.manager import CacheManager
from .cache.refresher import CacheRefresher
from .config import Settings, get_settings
from .docs.manifest import SyncManifest
from .docs.sync import MANIFEST_OBJECT_SUFFIX, DocsSyncService
from .llm.factory import build_llm_client
from .llm.protocol import LLMClient
from .logging_conf import configure_logging, get_logger
from .memory.long_term import LongTermMemory
from .memory.orchestrator import MemoryOrchestrator
from .memory.short_term import ShortTermMemory
from .routes import (
    ask_router,
    docs_router,
    health_router,
    memory_router,
    sessions_router,
)
from .schema import AgentSchema


def _rate_limit_key(request: Request) -> str:
    """Bucket rate-limit quotas by bearer token when present, else remote IP."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return get_remote_address(request)


def _materialize_schema_tree(source: str, dest_dir: Path) -> Path:
    """Download a schema bundle (agent_schema.yaml + prompts/*) from GCS if needed.

    `source` may be either a local path or a `gs://bucket/prefix/agent_schema.yaml`
    URL; returns the local path to the YAML file. Prompts referenced by relative
    paths get mirrored alongside it so the existing resolution logic keeps
    working unchanged.
    """
    if not source.startswith("gs://"):
        return Path(source)

    from urllib.parse import urlparse

    from google.cloud import storage  # type: ignore[attr-defined]

    parsed = urlparse(source)
    bucket_name = parsed.netloc
    yaml_object = parsed.path.lstrip("/")
    prefix = yaml_object.rsplit("/", 1)[0] + "/" if "/" in yaml_object else ""

    dest_dir.mkdir(parents=True, exist_ok=True)
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    for blob in bucket.list_blobs(prefix=prefix):
        rel = blob.name[len(prefix) :]
        if not rel:
            continue
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(target))

    local_yaml = dest_dir / yaml_object.rsplit("/", 1)[-1]
    return local_yaml


def _load_schema(path: Path) -> AgentSchema:
    if path.exists():
        return AgentSchema.from_yaml(path)
    # Fallback so unit tests and local smoke tests do not require a file.
    return AgentSchema.model_validate(
        {
            "apiVersion": "expert-agent/v1",
            "kind": "AgentSchema",
            "metadata": {"name": "example-expert", "version": __version__},
            "spec": {"identity": {"system_prompt": "You are a specialist agent."}},
        }
    )


def _resolve_system_instruction(schema: AgentSchema, schema_path: Path) -> str:
    identity = schema.spec.identity
    if identity.system_prompt:
        return identity.system_prompt
    assert identity.system_prompt_file is not None
    prompt_path = Path(identity.system_prompt_file)
    if not prompt_path.is_absolute():
        prompt_path = (schema_path.parent / prompt_path).resolve()
    return prompt_path.read_text(encoding="utf-8")


async def _load_manifest_from_gcs(
    gcs_client: Any, bucket: str, agent_id: str
) -> SyncManifest | None:
    key = f"{agent_id}/{MANIFEST_OBJECT_SUFFIX}"
    raw = await gcs_client.download_bytes(bucket, key)
    if raw is None:
        return None
    try:
        return SyncManifest.model_validate_json(raw)
    except Exception:  # pragma: no cover - corrupt manifest edge case
        return None


def _build_firestore_client(settings: Settings) -> Any:
    """Best-effort Firestore client construction with a test fallback."""
    if settings.app_env == "test":
        try:
            from mockfirestore import MockFirestore  # type: ignore[import-untyped]

            return MockFirestore()
        except Exception:  # pragma: no cover - mock-firestore optional
            return None
    try:
        from google.cloud import firestore

        kwargs: dict[str, Any] = {}
        if settings.gcp_project:
            kwargs["project"] = settings.gcp_project
        return firestore.Client(**kwargs)
    except Exception as exc:
        structlog.get_logger(__name__).warning("firestore.unavailable", error=str(exc))
        return None


def _build_gcs_client(settings: Settings) -> Any:
    """Thin wrapper over `google-cloud-storage`, mirroring the GcsClient Protocol."""
    if settings.app_env == "test" or not settings.docs_bucket:
        from .docs.sync import InMemoryGcsClient

        return InMemoryGcsClient()

    from google.cloud import storage  # type: ignore[attr-defined]

    client = storage.Client(project=settings.gcp_project or None)

    class _RealGcsClient:
        async def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
            def _upload() -> None:
                blob = client.bucket(bucket).blob(key)
                blob.upload_from_string(data, content_type=content_type)

            await asyncio.to_thread(_upload)

        async def upload_file(self, bucket: str, key: str, path: Path, content_type: str) -> None:
            def _upload() -> None:
                blob = client.bucket(bucket).blob(key)
                blob.upload_from_filename(str(path), content_type=content_type)

            await asyncio.to_thread(_upload)

        async def download_bytes(self, bucket: str, key: str) -> bytes | None:
            def _download() -> bytes | None:
                blob = client.bucket(bucket).blob(key)
                if not blob.exists():
                    return None
                data: bytes = blob.download_as_bytes()
                return data

            return await asyncio.to_thread(_download)

        async def delete(self, bucket: str, key: str) -> None:
            def _delete() -> None:
                blob = client.bucket(bucket).blob(key)
                if blob.exists():
                    blob.delete()

            await asyncio.to_thread(_delete)

    return _RealGcsClient()


def _build_long_term(schema: AgentSchema, settings: Settings) -> LongTermMemory | None:
    if not schema.spec.memory.long_term.enabled:
        return None
    if settings.app_env == "test":
        return None
    try:
        return LongTermMemory(
            collection_name=settings.chroma_collection_name,
            chroma_host=settings.mempalace_chroma_host,
            chroma_port=settings.mempalace_chroma_port,
            chroma_ssl=settings.mempalace_chroma_ssl,
        )
    except Exception as exc:
        structlog.get_logger(__name__).warning("long_term.unavailable", error=str(exc))
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger = get_logger(__name__)

    raw_schema_path = str(settings.schema_path)
    if raw_schema_path.startswith("gs://"):
        schema_path = _materialize_schema_tree(raw_schema_path, Path("/tmp/agent-schema"))
    else:
        schema_path = Path(settings.schema_path)
    schema = _load_schema(schema_path)
    app.state.schema = schema

    try:
        system_instruction = _resolve_system_instruction(schema, schema_path)
    except FileNotFoundError:
        system_instruction = "You are a specialist agent."

    llm: LLMClient | None = None
    try:
        llm = build_llm_client(schema, settings)
    except Exception as exc:
        logger.warning("llm.unavailable", error=str(exc))

    firestore_client = _build_firestore_client(settings)
    gcs_client = _build_gcs_client(settings)

    app.state.llm = llm
    app.state.firestore_client = firestore_client
    app.state.gcs_client = gcs_client

    cache_manager: CacheManager | None = None
    refresher: CacheRefresher | None = None
    docs_sync: DocsSyncService | None = None

    if llm is not None and firestore_client is not None:

        async def _manifest_loader() -> SyncManifest | None:
            return await _load_manifest_from_gcs(gcs_client, settings.docs_bucket, schema.agent_id)

        cache_manager = CacheManager(
            agent_id=schema.agent_id,
            llm=llm,
            firestore_client=firestore_client,
            system_instruction=system_instruction,
            ttl_seconds=schema.spec.context_cache.ttl_seconds,
            manifest_loader=_manifest_loader,
        )
        docs_dir = schema.spec.knowledge.reference_docs_dir
        if not docs_dir.is_absolute():
            docs_dir = (schema_path.parent / docs_dir).resolve()
        docs_sync = DocsSyncService(
            agent_id=schema.agent_id,
            docs_bucket=settings.docs_bucket,
            firestore_client=firestore_client,
            gcs_client=gcs_client,
            cache_manager=cache_manager,
            docs_dir=docs_dir,
            include_patterns=schema.spec.knowledge.include_patterns,
            exclude_patterns=schema.spec.knowledge.exclude_patterns,
        )
        if schema.spec.context_cache.enabled:
            # Warm the cache in the background instead of blocking startup.
            # A full recreate (File API uploads + cachedContents POST) scales
            # with corpus size and can exceed Cloud Run's 240s startup-probe
            # window for large corpora, which kills the instance before it
            # ever binds the port. The first request after a cold start may
            # pay the recreate penalty, but the instance always comes up.
            prewarm_manager = cache_manager

            async def _prewarm_cache() -> None:
                try:
                    await prewarm_manager.get_or_create()
                    logger.info("cache.prewarm_complete")
                except Exception as exc:
                    logger.warning("cache.prewarm_failed", error=str(exc))

            app.state.cache_prewarm_task = asyncio.create_task(_prewarm_cache())

            refresher = CacheRefresher(
                llm=llm,
                cache_manager=cache_manager,
                ttl_seconds=schema.spec.context_cache.ttl_seconds,
                refresh_before_expiry_seconds=schema.spec.context_cache.refresh_before_expiry_seconds,
            )
            await refresher.start()

    app.state.cache_manager = cache_manager
    app.state.docs_sync = docs_sync
    app.state.cache_refresher = refresher

    short_term: ShortTermMemory | None = None
    if firestore_client is not None:
        short_term = ShortTermMemory(agent_id=schema.agent_id, firestore_client=firestore_client)
    app.state.short_term = short_term

    long_term = _build_long_term(schema, settings)
    app.state.long_term = long_term

    if short_term is not None:
        orchestrator = MemoryOrchestrator(
            short_term=short_term,
            long_term=long_term,
            llm=llm,
            buffer_size=schema.spec.memory.short_term.buffer_size,
            max_recall_results=schema.spec.memory.long_term.max_recall_results,
        )
        app.state.orchestrator = orchestrator
    else:
        app.state.orchestrator = None

    logger.info(
        "app.ready",
        agent_id=schema.agent_id,
        version=__version__,
        env=settings.app_env,
        llm=bool(llm),
        firestore=bool(firestore_client),
        long_term=bool(long_term),
    )

    try:
        yield
    finally:
        logger.info("app.shutdown.begin")
        prewarm_task = getattr(app.state, "cache_prewarm_task", None)
        if prewarm_task is not None and not prewarm_task.done():
            prewarm_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await prewarm_task
        if refresher is not None:
            await refresher.stop()
        if long_term is not None:
            with contextlib.suppress(Exception):
                await long_term.close()
        if llm is not None:
            with contextlib.suppress(Exception):
                await llm.close()
        logger.info("app.shutdown.complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app with the given (or cached) settings."""
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    limiter = Limiter(key_func=_rate_limit_key, default_limits=["30/minute"])

    app = FastAPI(
        title="expert-agent",
        version=__version__,
        description="Ultra-specialist AI agent backend.",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.limiter = limiter

    async def _rate_limit_handler(_: Request, exc: Exception) -> Response:
        detail = getattr(exc, "detail", "limit exceeded")
        return Response(
            content=f'{{"detail":"rate limit exceeded: {detail}"}}',
            status_code=429,
            media_type="application/json",
        )

    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allow_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    app.include_router(health_router)
    app.include_router(docs_router)
    app.include_router(ask_router)
    app.include_router(sessions_router)
    app.include_router(memory_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()


def run() -> None:
    """`expert-agent-backend` console script entrypoint."""
    import os

    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_config=None,
    )


__all__ = ["app", "create_app", "lifespan", "run"]
