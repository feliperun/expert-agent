"""`expert sync` — push the local knowledge base to a running agent.

The local file list (with sha256 + size) is POSTed to `{endpoint}/docs/sync`.
The server replies with a diff describing added/updated/removed files. This
triggers a Context Cache rebuild on the runtime side.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from app.schema import AgentSchema

from ..config import make_http_client
from ..context import resolve as resolve_context
from ..ui import console, print_diff_table, print_error, print_info, print_success


def _iter_matching_files(
    root: Path,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> list[Path]:
    matched: set[Path] = set()
    for pattern in include_patterns:
        matched.update(p for p in root.rglob(pattern) if p.is_file())
    if exclude_patterns:
        excluded: set[Path] = set()
        for pattern in exclude_patterns:
            excluded.update(p for p in root.rglob(pattern) if p.is_file())
        matched -= excluded
    return sorted(matched)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(schema: AgentSchema, base_dir: Path) -> dict[str, Any]:
    docs_dir = (base_dir / schema.spec.knowledge.reference_docs_dir).resolve()
    files = _iter_matching_files(
        docs_dir,
        schema.spec.knowledge.include_patterns,
        schema.spec.knowledge.exclude_patterns,
    )
    entries: list[dict[str, Any]] = []
    for file_path in files:
        try:
            rel = file_path.relative_to(docs_dir)
        except ValueError:
            rel = file_path
        entries.append(
            {
                "path": str(rel),
                "sha256": _sha256(file_path),
                "size": file_path.stat().st_size,
            }
        )
    return {
        "agent_id": schema.agent_id,
        "schema_version": schema.metadata.version,
        "files": entries,
    }


async def _post_sync(
    endpoint: str,
    api_key: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    async with make_http_client(endpoint=endpoint, api_key=api_key) as client:
        response = await client.post("/docs/sync", json=manifest)
        response.raise_for_status()
        body = response.json()
        assert isinstance(body, dict)
        return body


def cmd(
    agent: Annotated[
        str | None,
        typer.Option("--agent", "-a", help="Agent name from the workspace."),
    ] = None,
    endpoint: Annotated[
        str | None,
        typer.Option(
            "--endpoint",
            envvar="EXPERT_AGENT_ENDPOINT",
            help="Override the agent's endpoint (defaults to workspace/env value).",
        ),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            envvar="EXPERT_AGENT_API_KEY",
            help="Override the agent's admin bearer token.",
        ),
    ] = None,
    schema_path: Annotated[
        Path | None,
        typer.Option("--schema", "-s", help="Explicit path to agent_schema.yaml."),
    ] = None,
) -> None:
    """Upload the local knowledge base and trigger a Context Cache rebuild."""
    ctx = resolve_context(
        agent=agent,
        schema=schema_path,
        endpoint=endpoint,
        api_key=api_key,
        require_remote=True,
    )
    schema_path = ctx.schema_path
    endpoint, api_key = ctx.require_remote()
    if not schema_path.is_file():
        print_error(f"schema file not found: {schema_path}")
        raise typer.Exit(code=1)
    if ctx.selector_source not in ("single", "schema-flag"):
        print_info(f"agent [cyan]{ctx.name}[/cyan] ({ctx.selector_source})")

    try:
        schema = AgentSchema.from_yaml(schema_path)
    except Exception as exc:
        print_error(f"failed to load schema: {exc}")
        raise typer.Exit(code=1) from exc

    base_dir = schema_path.parent
    manifest = _build_manifest(schema, base_dir)
    print_info(
        f"Prepared manifest with {len(manifest['files'])} file(s) for agent "
        f"[cyan]{schema.agent_id}[/cyan]."
    )

    try:
        diff = asyncio.run(_post_sync(endpoint.rstrip("/"), api_key, manifest))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            print_error(f"authentication failed ({status}): check EXPERT_AGENT_API_KEY.")
            raise typer.Exit(code=3) from exc
        print_error(f"server returned {status}: {exc.response.text[:200]}")
        raise typer.Exit(code=2) from exc
    except httpx.HTTPError as exc:
        print_error(f"network error: {exc}")
        raise typer.Exit(code=2) from exc

    print_diff_table(diff)
    console.print()
    print_success("Sync complete — context cache will be rebuilt shortly.")
