"""`expert test` — run the packaged Robot Framework end-to-end kit.

This command resolves the `.robot` suites that ship inside the `expert` wheel
(under `expert.testkit.suites`) so that private agent repositories only need
to install `expert-agent[test]` to run the *same* validated E2E suite that
expert-agent itself uses. No git submodules, no vendoring.

Variables resolve from env vars (`EXPERT_AGENT_*`) by default, but can be
overridden ad-hoc via `--var KEY:value`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from ..context import resolve as resolve_context
from ..ui import console, print_error, print_info, print_success

# Canonical order of the packaged suites. The numeric prefixes keep `robot`
# discovery deterministic across filesystems.
_DEFAULT_SUITES: tuple[str, ...] = (
    "01_validate",
    "02_create",
    "03_update",
    "04_deploy",
    "05_ask_latency",
    "06_sessions",
)


def cmd(
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            "-a",
            help="Agent name from the workspace. Resolved via `expert agents`.",
        ),
    ] = None,
    suite: Annotated[
        list[str] | None,
        typer.Option(
            "--suite",
            "-S",
            help=(
                "Run only the given suite(s) by stem (e.g. '05_ask_latency'). "
                "Can be passed multiple times. Default: all."
            ),
        ),
    ] = None,
    include: Annotated[
        list[str] | None,
        typer.Option("--include", "-i", help="Robot --include tag filter."),
    ] = None,
    exclude: Annotated[
        list[str] | None,
        typer.Option("--exclude", "-e", help="Robot --exclude tag filter."),
    ] = None,
    variable: Annotated[
        list[str] | None,
        typer.Option(
            "--var",
            "-v",
            help="Robot --variable KEY:value override. Can be repeated.",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory for report.html / log.html / output.xml.",
        ),
    ] = Path("./expert-e2e-results"),
    schema: Annotated[
        Path | None,
        typer.Option(
            "--schema",
            "-s",
            help="Explicit path to agent_schema.yaml (bypasses workspace resolution).",
        ),
    ] = None,
    endpoint: Annotated[
        str | None,
        typer.Option("--endpoint", help="Override the agent's endpoint."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="Override the agent's admin bearer token."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Parse and list suites without executing them."),
    ] = False,
    list_suites: Annotated[
        bool,
        typer.Option("--list", help="Print the available suites and exit."),
    ] = False,
) -> None:
    """Run the packaged end-to-end test kit against the current agent."""
    try:
        from ..testkit import suites_dir
    except ImportError as exc:  # pragma: no cover — import-time guard
        print_error(
            "Packaged test kit not found. Reinstall with `uv tool install 'expert-agent[test]'`."
        )
        raise typer.Exit(code=2) from exc

    root = suites_dir()
    if not root.is_dir():
        print_error(f"Test kit directory missing at {root}. Broken install?")
        raise typer.Exit(code=2)

    available = sorted(p.stem for p in root.glob("*.robot") if p.stem != "__init__")
    if list_suites:
        console.print("[bold]Available suites:[/bold]")
        for name in available:
            console.print(f"  • {name}")
        raise typer.Exit(code=0)

    chosen = _resolve_suites(available, suite)
    if not chosen:
        print_error(f"No suites matched selection {suite!r}. Available: {available}")
        raise typer.Exit(code=2)

    # Resolve the agent context (supports --agent / @alias / `expert use`)
    # so that the packaged Robot suites see fully-populated env vars even
    # in multi-agent workspaces without requiring --var or --endpoint.
    # We fall back to a bare resolve (schema-only) so that the offline
    # suites still work when endpoint/api_key are not configured.
    ctx = resolve_context(
        agent=agent,
        schema=schema,
        endpoint=endpoint,
        api_key=api_key,
    )
    if ctx.selector_source not in ("single", "schema-flag"):
        print_info(f"→ [cyan]{ctx.name}[/cyan] ({ctx.selector_source})")

    env_overrides: dict[str, str] = {"EXPERT_AGENT_SCHEMA": str(ctx.schema_path)}
    if ctx.endpoint:
        env_overrides["EXPERT_AGENT_ENDPOINT"] = ctx.endpoint
    if ctx.api_key:
        env_overrides["EXPERT_AGENT_API_KEY"] = ctx.api_key
    for key, value in env_overrides.items():
        os.environ[key] = value

    paths = [root / f"{name}.robot" for name in chosen]

    if dry_run:
        print_info("[dry-run] would execute robot on:")
        for p in paths:
            console.print(f"  • {p}")
        raise typer.Exit(code=0)

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from robot.api import ExecutionResult  # noqa: F401
        from robot.run import run_cli
    except ImportError as exc:
        print_error(
            "robotframework is not installed. "
            "Reinstall with `uv tool install 'expert-agent[test]'`."
        )
        raise typer.Exit(code=2) from exc

    args: list[str] = [
        "--outputdir",
        str(output_dir),
        "--name",
        "expert-agent-e2e",
    ]
    for tag in include or []:
        args.extend(["--include", tag])
    for tag in exclude or []:
        args.extend(["--exclude", tag])
    for var in variable or []:
        args.extend(["--variable", var])
    # Robot needs the library directory on its module path so it can import
    # `ExpertLibrary.py` that sits alongside the suites.
    sys.path.insert(0, str(root.parent))
    args.extend(str(p) for p in paths)

    print_info(f"running {len(paths)} suite(s) — reports in {output_dir.resolve()}")
    try:
        rc = run_cli(args, exit=False)
    except SystemExit as exc:  # run_cli may still raise depending on version
        rc = int(exc.code) if exc.code is not None else 1

    if rc == 0:
        print_success("All suites passed.")
    else:
        print_error(f"Robot exited with rc={rc}. See {output_dir}/report.html")
    raise typer.Exit(code=rc)


def _resolve_suites(available: list[str], chosen: list[str] | None) -> list[str]:
    if not chosen:
        ordered = [name for name in _DEFAULT_SUITES if name in available]
        extras = [name for name in available if name not in ordered]
        return ordered + extras
    resolved: list[str] = []
    for name in chosen:
        if name in available:
            resolved.append(name)
            continue
        matches = [a for a in available if name in a]
        if len(matches) == 1:
            resolved.append(matches[0])
        elif not matches:
            print_error(f"No suite matches '{name}'. Available: {available}")
        else:
            print_error(f"Ambiguous suite '{name}'. Matches: {matches}")
    return resolved
