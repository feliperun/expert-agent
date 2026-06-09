"""End-to-end `/docs/sync` orchestration.

Steps (§8 of the plan):

1. Acquire Firestore lock (`agents/{agent_id}/state/sync_lock`, TTL 15min).
2. Load current manifest from GCS.
3. Compute incoming manifest (from payload or local walk).
4. Diff + upload added/changed files to GCS.
5. If any change: recreate the Context Cache.
6. Persist new manifest.
7. Release lock.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import structlog
from pydantic import BaseModel, ConfigDict, Field

from ..cache.manager import CacheManager
from .manifest import (
    FileEntry,
    ManifestDiff,
    SyncManifest,
    diff_manifests,
    guess_mime,
    manifest_from_directory,
)

logger = structlog.get_logger(__name__)

MANIFEST_OBJECT_SUFFIX = "_state/sync_manifest.json"
LOCK_TTL = timedelta(minutes=15)


class SyncLockError(RuntimeError):
    """Raised when `/docs/sync` cannot acquire the Firestore lock."""


class GcsClient(Protocol):
    """Minimal async GCS interface — real impl wraps `google-cloud-storage`."""

    async def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None: ...

    async def upload_file(self, bucket: str, key: str, path: Path, content_type: str) -> None: ...

    async def download_bytes(self, bucket: str, key: str) -> bytes | None: ...

    async def delete(self, bucket: str, key: str) -> None: ...


@dataclass(slots=True)
class SyncResult:
    """Return value of `DocsSyncService.sync`."""

    diff: ManifestDiff
    manifest_sha: str
    cache_recreated: bool


class LocalFile(BaseModel):
    """A single file in the /docs/sync payload."""

    model_config = ConfigDict(extra="ignore")

    path: str = Field(min_length=1)
    local_path: Path | None = None
    mime_type: str | None = None
    sha256: str | None = None
    size: int | None = None


class DocsSyncRequest(BaseModel):
    """Payload of `POST /docs/sync`.

    `files` is optional — when empty the service walks the local `docs_dir`
    configured in the agent schema.
    """

    model_config = ConfigDict(extra="forbid")

    files: list[LocalFile] | None = None


class DocsSyncResponse(BaseModel):
    """JSON response of `POST /docs/sync`."""

    model_config = ConfigDict(extra="forbid")

    added: list[str]
    removed: list[str]
    changed: list[str]
    manifest_sha: str
    cache_recreated: bool


class DocsSyncService:
    """Encapsulates the `/docs/sync` workflow so it can be reused by the CLI."""

    def __init__(
        self,
        *,
        agent_id: str,
        docs_bucket: str,
        firestore_client: Any,
        gcs_client: GcsClient,
        cache_manager: CacheManager,
        docs_dir: Path,
        include_patterns: list[str],
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._bucket = docs_bucket
        self._firestore = firestore_client
        self._gcs = gcs_client
        self._cache_manager = cache_manager
        self._docs_dir = docs_dir
        self._include = include_patterns
        self._exclude = exclude_patterns or []

    def _object_key(self, relpath: str, sha256: str) -> str:
        """Layout: `gs://{bucket}/{agent_id}/{sha256[:8]}/{basename}`."""
        basename = Path(relpath).name
        return f"{self._agent_id}/{sha256[:8]}/{basename}"

    def _manifest_key(self) -> str:
        return f"{self._agent_id}/{MANIFEST_OBJECT_SUFFIX}"

    def _lock_ref(self) -> Any:
        return (
            self._firestore.collection("agents")
            .document(self._agent_id)
            .collection("state")
            .document("sync_lock")
        )

    async def _acquire_lock(self) -> str:
        """Acquire an expiring Firestore lock. Returns the caller-side token."""
        token = uuid.uuid4().hex
        now = datetime.now(tz=UTC)
        expires_at = now + LOCK_TTL

        def _try_acquire() -> bool:
            ref = self._lock_ref()
            snap = ref.get()
            if getattr(snap, "exists", False):
                data = snap.to_dict() or {}
                current_expiry = data.get("expires_at")
                if isinstance(current_expiry, datetime) and current_expiry > now:
                    return False
            ref.set({"holder": token, "expires_at": expires_at, "acquired_at": now})
            return True

        acquired = await asyncio.to_thread(_try_acquire)
        if not acquired:
            raise SyncLockError("sync_lock held by another caller")
        return token

    async def _release_lock(self, token: str) -> None:
        def _release() -> None:
            ref = self._lock_ref()
            snap = ref.get()
            if not getattr(snap, "exists", False):
                return
            data = snap.to_dict() or {}
            if data.get("holder") == token:
                ref.delete()

        await asyncio.to_thread(_release)

    async def _load_current_manifest(self) -> SyncManifest:
        raw = await self._gcs.download_bytes(self._bucket, self._manifest_key())
        if raw is None:
            return SyncManifest()
        try:
            return SyncManifest.model_validate_json(raw)
        except Exception as exc:
            logger.warning("docs.manifest.corrupt", error=str(exc))
            return SyncManifest()

    async def _persist_manifest(self, manifest: SyncManifest) -> None:
        payload = manifest.model_dump_json().encode("utf-8")
        await self._gcs.upload_bytes(
            self._bucket, self._manifest_key(), payload, "application/json"
        )

    async def _build_incoming_manifest(self, request: DocsSyncRequest) -> SyncManifest:
        if request.files:
            return await asyncio.to_thread(self._manifest_from_payload, request.files)
        return await asyncio.to_thread(
            manifest_from_directory,
            self._docs_dir,
            include=self._include,
            exclude=self._exclude,
            gcs_uri_for=self._gcs_uri_for_directory,
        )

    def _gcs_uri_for_directory(self, relpath: str, entry: FileEntry) -> str:
        return f"gs://{self._bucket}/{self._object_key(relpath, entry.sha256)}"

    def _manifest_from_payload(self, files: list[LocalFile]) -> SyncManifest:
        from .manifest import compute_file_sha256

        entries: dict[str, FileEntry] = {}
        for item in files:
            if item.local_path is None:
                if item.sha256 is not None and item.size is not None:
                    mime = item.mime_type or guess_mime(Path(item.path))
                    entries[item.path] = FileEntry(
                        sha256=item.sha256,
                        size=item.size,
                        gcs_uri=f"gs://{self._bucket}/{self._object_key(item.path, item.sha256)}",
                        mime_type=mime,
                        updated_at=datetime.now(tz=UTC),
                    )
                    continue
                else:
                    raise ValueError(
                        f"file {item.path!r} has no local_path and missing sha256/size; payload uploads require resolved paths"
                    )
            src = Path(item.local_path)
            if not src.exists():
                raise FileNotFoundError(f"file not found: {src}")
            sha = compute_file_sha256(src)
            mime = item.mime_type or guess_mime(src)
            stat = src.stat()
            entries[item.path] = FileEntry(
                sha256=sha,
                size=stat.st_size,
                gcs_uri=f"gs://{self._bucket}/{self._object_key(item.path, sha)}",
                mime_type=mime,
                updated_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            )
        return SyncManifest(files=entries)

    async def _upload_changed(
        self,
        diff: ManifestDiff,
        incoming: SyncManifest,
        resolver: dict[str, Path],
    ) -> None:
        paths_to_upload = [*diff.added, *diff.changed]
        for relpath in paths_to_upload:
            entry = incoming.files[relpath]
            local = resolver.get(relpath)
            key = self._object_key(relpath, entry.sha256)
            if local is not None:
                await self._gcs.upload_file(self._bucket, key, local, entry.mime_type)
            else:
                src = self._docs_dir / relpath
                if src.is_file():
                    with src.open("rb") as fh:
                        data = fh.read()
                    await self._gcs.upload_bytes(self._bucket, key, data, entry.mime_type)
                    continue
                # Remote sync: CLI posts sha256/size; bytes may already be in GCS.
                existing = await self._gcs.download_bytes(self._bucket, key)
                if existing is None:
                    raise FileNotFoundError(
                        f"file {relpath!r} not found under {self._docs_dir} "
                        f"and not pre-uploaded to gs://{self._bucket}/{key}"
                    )

    async def _delete_removed(self, diff: ManifestDiff, old: SyncManifest) -> None:
        for relpath in diff.removed:
            entry = old.files.get(relpath)
            if entry is None:
                continue
            key = self._object_key(relpath, entry.sha256)
            await self._gcs.delete(self._bucket, key)

    async def sync(self, request: DocsSyncRequest | None = None) -> SyncResult:
        """Run the full sync pipeline and return the computed diff."""
        request = request or DocsSyncRequest()
        token = await self._acquire_lock()
        try:
            current = await self._load_current_manifest()
            incoming = await self._build_incoming_manifest(request)
            diff = diff_manifests(current, incoming)

            resolver: dict[str, Path] = {}
            if request.files:
                for f in request.files:
                    if f.local_path is not None:
                        resolver[f.path] = Path(f.local_path)

            await self._upload_changed(diff, incoming, resolver)
            await self._delete_removed(diff, current)

            cache_recreated = False
            if diff.has_changes:
                await self._cache_manager.recreate(incoming)
                cache_recreated = True

            await self._persist_manifest(incoming)
            logger.info(
                "docs.sync.complete",
                added=len(diff.added),
                removed=len(diff.removed),
                changed=len(diff.changed),
                cache_recreated=cache_recreated,
            )
            return SyncResult(
                diff=diff, manifest_sha=incoming.sha256(), cache_recreated=cache_recreated
            )
        finally:
            await self._release_lock(token)

    @staticmethod
    def diff_to_response(result: SyncResult) -> DocsSyncResponse:
        return DocsSyncResponse(
            added=result.diff.added,
            removed=result.diff.removed,
            changed=result.diff.changed,
            manifest_sha=result.manifest_sha,
            cache_recreated=result.cache_recreated,
        )


class InMemoryGcsClient:
    """Testing double implementing the GcsClient protocol backed by a dict."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self._objects[(bucket, key)] = (data, content_type)

    async def upload_file(self, bucket: str, key: str, path: Path, content_type: str) -> None:
        with path.open("rb") as fh:
            data = fh.read()
        self._objects[(bucket, key)] = (data, content_type)

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        item = self._objects.get((bucket, key))
        return item[0] if item else None

    async def delete(self, bucket: str, key: str) -> None:
        self._objects.pop((bucket, key), None)

    def dump(self) -> dict[tuple[str, str], bytes]:
        return {k: v[0] for k, v in self._objects.items()}

    def sync_manifest_payload(self, bucket: str, agent_id: str) -> bytes | None:
        return self._objects.get((bucket, f"{agent_id}/{MANIFEST_OBJECT_SUFFIX}"), (None,))[0]

    def as_dict(self) -> dict[str, Any]:  # pragma: no cover - introspection helper
        return {
            f"gs://{b}/{k}": json.loads(v[0]) if k.endswith(".json") else len(v[0])
            for (b, k), v in self._objects.items()
        }


__all__ = [
    "DocsSyncRequest",
    "DocsSyncResponse",
    "DocsSyncService",
    "GcsClient",
    "InMemoryGcsClient",
    "LocalFile",
    "SyncLockError",
    "SyncResult",
]
