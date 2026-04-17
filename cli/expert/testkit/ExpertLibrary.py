"""Robot Framework library for end-to-end testing of expert-agent deployments.

Wraps the HTTP surface (`/health`, `/ready`, `/ask`, `/sessions`, `/docs/sync`)
and the `expert` CLI so that `.robot` suites read as plain English.

All keywords are thin and composable — heavy assertions live in the suites.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from robot.api import logger
from robot.api.deco import keyword, library

_DEFAULT_USER_ID = "expert-e2e"


@dataclass
class _AskResult:
    status: int
    body: dict[str, Any]
    elapsed_ms: int
    session_id: str | None = None
    raw: str = ""
    ttft_ms: int | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


@library(scope="SUITE", auto_keywords=False)
class ExpertLibrary:
    """Robot Framework keywords for expert-agent E2E suites."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._endpoint = (endpoint or os.environ.get("EXPERT_AGENT_ENDPOINT") or "").rstrip("/")
        self._api_key = api_key or os.environ.get("EXPERT_AGENT_API_KEY") or ""
        self._timeout = float(os.environ.get("EXPERT_AGENT_TIMEOUT_SECONDS") or timeout)

    # ------------------------------------------------------------------
    # CLI wrappers (exercise the packaged `expert` binary)
    # ------------------------------------------------------------------

    @keyword("Run Expert CLI")
    def run_cli(
        self, *args: str, expect_rc: int | None = 0, cwd: str | None = None
    ) -> dict[str, Any]:
        """Execute `expert <args>` and return `{rc, stdout, stderr, elapsed_ms}`.

        Fails if the exit code differs from ``expect_rc`` (use ``expect_rc=None``
        to skip the check entirely). ``expect_rc`` is typed ``int | None`` so
        Robot Framework's dynamic-argument converter accepts ``${None}`` from
        suite files without trying to coerce it into ``int`` (which fails).
        """
        binary = shutil.which("expert")
        if binary is None:
            raise AssertionError(
                "`expert` binary not on PATH — install with `uv tool install expert-agent`"
            )
        cmd = [binary, *args]
        logger.info(f"$ {shlex.join(cmd)}")
        started = time.monotonic()
        proc = subprocess.run(  # command is trusted, args come from the suite
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=self._timeout + 30,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if expect_rc is not None and proc.returncode != expect_rc:
            raise AssertionError(
                f"expert {' '.join(args)} exited {proc.returncode} "
                f"(expected {expect_rc})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        return {
            "rc": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed_ms": elapsed_ms,
        }

    # ------------------------------------------------------------------
    # HTTP wrappers (direct backend calls; complement CLI-based keywords)
    # ------------------------------------------------------------------

    @keyword("Probe Health Endpoint")
    def probe_health(self) -> dict[str, Any]:
        """GET `/health` — must return 200 and `{status: "ok"}` or similar."""
        resp = self._client().get("/health")
        return {"status": resp.status_code, "body": _safe_json(resp)}

    @keyword("Probe Ready Endpoint")
    def probe_ready(self) -> dict[str, Any]:
        """GET `/ready` — should return 200 once the cache has been warmed."""
        resp = self._client().get("/ready")
        return {"status": resp.status_code, "body": _safe_json(resp)}

    @keyword("Ask Question")
    def ask_question(
        self,
        question: str,
        *,
        stream: bool = False,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> _AskResult:
        """POST `/ask` (streaming or JSON) and return a structured result."""
        sid = session_id or str(uuid.uuid4())
        uid = user_id or _DEFAULT_USER_ID
        payload: dict[str, Any] = {
            "user_id": uid,
            "session_id": sid,
            "message": question,
            "stream": stream,
        }

        if not stream:
            started = time.monotonic()
            resp = self._client().post("/ask", json=payload)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            body = _safe_json(resp)
            # Backend echoes request_id but not session_id — preserve what we
            # sent so the sessions suite can clean up afterwards.
            return _AskResult(
                status=resp.status_code,
                body=body,
                elapsed_ms=elapsed_ms,
                session_id=sid if resp.status_code == 200 else None,
                raw=resp.text,
            )

        return self._ask_stream(payload, session_id=sid)

    @keyword("Ask Question Unauthenticated")
    def ask_question_unauthenticated(self, question: str) -> dict[str, Any]:
        """POST `/ask` with *no* bearer token — must fail with 401."""
        with httpx.Client(
            base_url=self._endpoint,
            timeout=self._timeout,
            headers={"User-Agent": "expert-e2e"},
        ) as client:
            resp = client.post(
                "/ask",
                json={
                    "user_id": _DEFAULT_USER_ID,
                    "session_id": str(uuid.uuid4()),
                    "message": question,
                    "stream": False,
                },
            )
        return {"status": resp.status_code, "body": _safe_json(resp)}

    @keyword("List Sessions")
    def list_sessions(self, user_id: str | None = None) -> dict[str, Any]:
        uid = user_id or _DEFAULT_USER_ID
        resp = self._client().get("/sessions", params={"user_id": uid})
        return {"status": resp.status_code, "body": _safe_json(resp)}

    @keyword("Delete Session")
    def delete_session(self, session_id: str, user_id: str | None = None) -> dict[str, Any]:
        uid = user_id or _DEFAULT_USER_ID
        resp = self._client().delete(f"/sessions/{session_id}", params={"user_id": uid})
        return {"status": resp.status_code, "body": _safe_json(resp)}

    # ------------------------------------------------------------------
    # Schema helpers (for validate/create/update suites)
    # ------------------------------------------------------------------

    @keyword("Read Schema From Path")
    def read_schema(self, path: str) -> str:
        p = Path(path)
        if not p.is_file():
            raise AssertionError(f"schema not found: {path}")
        return p.read_text()

    @keyword("Write Temp Schema")
    def write_temp_schema(
        self,
        content: str,
        directory: str,
        source_schema: str | None = None,
    ) -> str:
        """Write ``content`` to ``directory/agent_schema.yaml`` and mirror the
        source project's ``prompts/`` and ``docs/`` dirs via symlinks so that
        relative paths inside the schema still resolve. If ``source_schema``
        is not given, uses the env variable ``EXPERT_AGENT_SCHEMA``.
        """
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "agent_schema.yaml"
        target.write_text(content)

        src = Path(source_schema or os.environ.get("EXPERT_AGENT_SCHEMA") or "")
        if src.is_file():
            root = src.parent
            for sub in ("prompts", "docs"):
                src_sub = root / sub
                dst_sub = target_dir / sub
                if src_sub.is_dir() and not dst_sub.exists():
                    # Fall back silently if the FS doesn't support symlinks;
                    # the suite will then fail with a clearer error message.
                    with contextlib.suppress(OSError):
                        dst_sub.symlink_to(src_sub, target_is_directory=True)
        return str(target)

    @keyword("Bump Schema Version")
    def bump_schema_version(self, content: str) -> str:
        """Return ``content`` with a trailing blank line appended.

        The schema contract rejects unknown keys (``extra='forbid'``), so the
        cheapest functional 'update' we can exercise without breaking contracts
        is adding/removing whitespace. This is enough to prove the
        validate-then-reload loop of the CLI.
        """
        stripped = content.rstrip() + "\n"
        return stripped + "\n"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        if not self._endpoint:
            raise AssertionError("EXPERT_AGENT_ENDPOINT is not set")
        headers = {
            "User-Agent": "expert-e2e",
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.Client(base_url=self._endpoint, headers=headers, timeout=self._timeout)

    def _ask_stream(self, payload: dict[str, Any], *, session_id: str | None = None) -> _AskResult:
        headers = {"Accept": "text/event-stream"}
        ttft_ms: int | None = None
        events: list[dict[str, Any]] = []
        chunks: list[str] = []

        started = time.monotonic()
        with (
            self._client() as client,
            client.stream("POST", "/ask", json=payload, headers=headers) as resp,
        ):
            status = resp.status_code
            current_event = ""
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if not data:
                        continue
                    if current_event == "token" and ttft_ms is None:
                        ttft_ms = int((time.monotonic() - started) * 1000)
                    try:
                        parsed: Any = json.loads(data)
                    except json.JSONDecodeError:
                        parsed = data
                    events.append({"event": current_event, "data": parsed})
                    if current_event == "token" and isinstance(parsed, dict):
                        chunks.append(str(parsed.get("text", "")))

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return _AskResult(
            status=status,
            body={"text": "".join(chunks)},
            elapsed_ms=elapsed_ms,
            ttft_ms=ttft_ms,
            session_id=session_id if status == 200 else None,
            raw="".join(chunks),
            events=events,
        )


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # intentional: return raw text on decode errors
        return {"raw": resp.text}
