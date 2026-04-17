"""`expert validate` — load and validate an `agent_schema.yaml` locally."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from app.schema import AgentSchema
from pydantic import ValidationError

from ..context import resolve as resolve_context
from ..ui import print_error, print_info, print_schema, print_success, print_warning


def _iter_matching_files(
    root: Path,
    include_patterns: list[str],
    exclude_patterns: list[str],
) -> list[Path]:
    """Return files under `root` matching include_patterns and not matched by excludes."""
    matched: set[Path] = set()
    for pattern in include_patterns:
        matched.update(p for p in root.rglob(pattern) if p.is_file())
    if exclude_patterns:
        excluded: set[Path] = set()
        for pattern in exclude_patterns:
            excluded.update(p for p in root.rglob(pattern) if p.is_file())
        matched -= excluded
    return sorted(matched)


def cmd(
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            "-a",
            help="Agent name (from expert.toml or sibling dirs). See `expert agents`.",
        ),
    ] = None,
    schema_path: Annotated[
        Path | None,
        typer.Option(
            "--schema",
            "-s",
            help="Explicit path to agent_schema.yaml (bypasses workspace resolution).",
        ),
    ] = None,
) -> None:
    """Validate an agent schema and its referenced filesystem layout."""
    ctx = resolve_context(agent=agent, schema=schema_path)
    schema_path = ctx.schema_path
    if not schema_path.is_file():
        print_error(f"schema file not found: {schema_path}")
        raise typer.Exit(code=1)
    if ctx.selector_source not in ("single", "schema-flag"):
        print_info(f"agent [cyan]{ctx.name}[/cyan] ({ctx.selector_source})")

    try:
        schema = AgentSchema.from_yaml(schema_path)
    except ValidationError as exc:
        print_error("schema validation failed:")
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            print_error(f"  {loc}: {err['msg']}")
        raise typer.Exit(code=1) from exc
    except (OSError, ValueError) as exc:
        print_error(f"failed to parse schema: {exc}")
        raise typer.Exit(code=1) from exc

    print_schema(schema)

    base_dir = schema_path.parent
    errors: list[str] = []
    warnings: list[str] = []

    prompt_file = schema.spec.identity.system_prompt_file
    if prompt_file is not None:
        resolved_prompt = (base_dir / prompt_file).resolve()
        if not resolved_prompt.is_file():
            errors.append(f"identity.system_prompt_file does not exist: {resolved_prompt}")

    docs_dir = (base_dir / schema.spec.knowledge.reference_docs_dir).resolve()
    if not docs_dir.is_dir():
        errors.append(f"knowledge.reference_docs_dir does not exist: {docs_dir}")
    else:
        matches = _iter_matching_files(
            docs_dir,
            schema.spec.knowledge.include_patterns,
            schema.spec.knowledge.exclude_patterns,
        )
        if not matches:
            errors.append(
                f"no files under {docs_dir} match include_patterns "
                f"{schema.spec.knowledge.include_patterns}"
            )
        elif len(matches) < 3:
            warnings.append(
                f"only {len(matches)} document(s) found — consider adding more reference material."
            )

    for warning in warnings:
        print_warning(warning)
    if errors:
        for err_msg in errors:
            print_error(err_msg)
        raise typer.Exit(code=1)

    print_success(f"Schema [cyan]{schema.agent_id}[/cyan] is valid.")
