"""`expert count-tokens` — estimate token usage of the knowledge base.

Uses `google.genai` for textual files. For PDF files we cannot count tokens
without uploading to GCS / the Files API, so we fall back to a heuristic
(size_kb * 0.25 tokens/byte ≈ 250 tokens per KB) and emit a WARN line.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer
from app.schema import AgentSchema

from ..context import resolve as resolve_context
from ..ui import console, print_error, print_info, print_success, print_warning

if TYPE_CHECKING:
    from google.genai import Client as GenaiClient

CACHE_SWEET_SPOT = 700_000
_TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".mdx"}
_PDF_SUFFIXES = {".pdf"}


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


def _make_client(api_key: str) -> GenaiClient:
    # TODO(expert-agent): allow Vertex credentials path alongside API-key mode.
    from google.genai import Client as GenaiClient

    return GenaiClient(api_key=api_key)


async def _count_text_tokens(client: GenaiClient, model: str, content: str) -> int:
    response = await client.aio.models.count_tokens(model=model, contents=content)
    return int(response.total_tokens or 0)


def _heuristic_pdf_tokens(size_bytes: int) -> int:
    size_kb = size_bytes / 1024.0
    return int(size_kb * 0.25 * 1024)


async def _count_all(
    client: GenaiClient,
    model: str,
    files: list[Path],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    total = 0
    for file_path in files:
        suffix = file_path.suffix.lower()
        size_bytes = file_path.stat().st_size
        if suffix in _TEXT_SUFFIXES or suffix == "":
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                warnings.append(f"{file_path}: not valid UTF-8, skipping token count.")
                rows.append(
                    {"path": file_path, "tokens": 0, "method": "skipped", "size": size_bytes}
                )
                continue
            tokens = await _count_text_tokens(client, model, text)
            rows.append(
                {"path": file_path, "tokens": tokens, "method": "genai", "size": size_bytes}
            )
        elif suffix in _PDF_SUFFIXES:
            tokens = _heuristic_pdf_tokens(size_bytes)
            warnings.append(
                f"{file_path}: PDF token count is a heuristic; "
                "upload to GCS for an exact measurement."
            )
            rows.append(
                {"path": file_path, "tokens": tokens, "method": "heuristic", "size": size_bytes}
            )
        else:
            try:
                text = file_path.read_text(encoding="utf-8")
                tokens = await _count_text_tokens(client, model, text)
                method = "genai"
            except (UnicodeDecodeError, OSError):
                tokens = _heuristic_pdf_tokens(size_bytes)
                method = "heuristic"
                warnings.append(f"{file_path}: unsupported type, falling back to heuristic.")
            rows.append({"path": file_path, "tokens": tokens, "method": method, "size": size_bytes})
        total += tokens
    return rows, total, warnings


def _render_table(rows: list[dict[str, Any]], root: Path) -> None:
    from rich.table import Table

    table = Table(title="Token count per file")
    table.add_column("File", overflow="fold")
    table.add_column("Size", justify="right")
    table.add_column("Method", justify="center")
    table.add_column("Tokens", justify="right")
    for row in rows:
        path = row["path"]
        rel = Path(path).resolve()
        with contextlib.suppress(ValueError):
            rel = rel.relative_to(root)
        method = str(row["method"])
        tokens = int(row["tokens"])
        size = int(row["size"])
        style = "yellow" if method == "heuristic" else "white"
        table.add_row(
            f"[{style}]{rel}[/{style}]",
            f"{size} B",
            method,
            f"{tokens:,}",
        )
    console.print(table)


def cmd(
    gemini_api_key: Annotated[
        str,
        typer.Option(
            "--gemini-api-key",
            envvar="GEMINI_API_KEY",
            help="API key for google-genai token counting.",
        ),
    ],
    agent: Annotated[
        str | None,
        typer.Option("--agent", "-a", help="Agent name from the workspace."),
    ] = None,
    schema_path: Annotated[
        Path | None,
        typer.Option(
            "--schema",
            "-s",
            help="Explicit path to agent_schema.yaml (bypasses workspace resolution).",
        ),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help="Model used for the count_tokens API call."),
    ] = "gemini-2.0-flash-exp",
) -> None:
    """Walk the knowledge base and sum the estimated token count per file."""
    ctx = resolve_context(agent=agent, schema=schema_path)
    schema_path = ctx.schema_path
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
    docs_dir = (base_dir / schema.spec.knowledge.reference_docs_dir).resolve()
    if not docs_dir.is_dir():
        print_error(f"reference_docs_dir does not exist: {docs_dir}")
        raise typer.Exit(code=1)

    files = _iter_matching_files(
        docs_dir,
        schema.spec.knowledge.include_patterns,
        schema.spec.knowledge.exclude_patterns,
    )
    if not files:
        print_warning(f"no files matched include_patterns under {docs_dir}")
        raise typer.Exit(code=0)

    print_info(f"Counting tokens for {len(files)} file(s) using model [cyan]{model}[/cyan]...")

    client = _make_client(gemini_api_key)
    try:
        rows, total, warnings = asyncio.run(_count_all(client, model, files))
    except Exception as exc:
        print_error(f"token counting failed: {exc}")
        raise typer.Exit(code=2) from exc

    _render_table(rows, docs_dir)
    for warning in warnings:
        print_warning(warning)

    print_success(f"Grand total: [bold]{total:,}[/bold] tokens across {len(files)} file(s).")
    if total > CACHE_SWEET_SPOT:
        print_warning(
            f"Total ({total:,}) exceeds Context Cache sweet spot of "
            f"{CACHE_SWEET_SPOT:,} tokens — consider splitting the corpus."
        )
