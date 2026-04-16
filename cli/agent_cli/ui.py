"""Shared Rich helpers used across commands.

The CLI follows a strict no-emoji policy in source code — visual cues come
exclusively from Rich colors, icons (drawn via Unicode box/arrow characters
that Rich supports) and markdown glyphs. No emoji characters are used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

if TYPE_CHECKING:
    from app.schema import AgentSchema

console = Console()


def print_error(msg: str) -> None:
    """Render an error line in bold red prefixed with `ERROR`."""
    console.print(f"[bold red]ERROR[/bold red] {msg}")


def print_success(msg: str) -> None:
    """Render a success line in green prefixed with a check mark."""
    console.print(f"[bold green]OK[/bold green] {msg}")


def print_warning(msg: str) -> None:
    """Render a warning line in yellow prefixed with `WARN`."""
    console.print(f"[bold yellow]WARN[/bold yellow] {msg}")


def print_info(msg: str) -> None:
    """Render a neutral informational line."""
    console.print(f"[bold cyan]INFO[/bold cyan] {msg}")


def print_diff_table(diff: dict[str, Any]) -> None:
    """Render a sync diff using a Rich `Table`.

    The expected input is a mapping such as:

    ```python
    {
        "added":   [{"path": "docs/a.md", "sha": "abc1234", "size": 1024}, ...],
        "updated": [...],
        "removed": [{"path": "docs/old.md", "sha": "def4567", "size": 512}, ...],
    }
    ```
    """
    table = Table(title="Sync diff", show_lines=False)
    table.add_column("Action", style="bold", no_wrap=True)
    table.add_column("Path", overflow="fold")
    table.add_column("SHA", no_wrap=True)
    table.add_column("Size", justify="right", no_wrap=True)

    actions: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("added", "green", list(diff.get("added", []) or [])),
        ("updated", "yellow", list(diff.get("updated", []) or [])),
        ("removed", "red", list(diff.get("removed", []) or [])),
    ]
    total = 0
    for action, color, entries in actions:
        for entry in entries:
            total += 1
            sha = str(entry.get("sha", ""))[:12]
            size = entry.get("size")
            size_str = _fmt_size(size) if isinstance(size, int) else "-"
            table.add_row(
                f"[{color}]{action}[/{color}]",
                str(entry.get("path", "")),
                sha,
                size_str,
            )

    if total == 0:
        console.print("[dim]No changes — remote is in sync with local.[/dim]")
        return
    console.print(table)


def print_schema(schema: AgentSchema) -> None:
    """Render an `AgentSchema` as a Rich `Tree`."""
    meta = schema.metadata
    spec = schema.spec
    tree = Tree(f"[bold]{meta.name}[/bold] [dim]v{meta.version}[/dim]")
    if meta.description:
        tree.add(f"[italic]{meta.description}[/italic]")

    model = tree.add("[bold]model[/bold]")
    model.add(f"provider: [cyan]{spec.model.provider}[/cyan]")
    model.add(f"name: [cyan]{spec.model.name}[/cyan]")
    model.add(f"temperature: {spec.model.temperature}")
    model.add(f"max_output_tokens: {spec.model.max_output_tokens}")

    identity = tree.add("[bold]identity[/bold]")
    if spec.identity.system_prompt_file is not None:
        identity.add(f"system_prompt_file: [cyan]{spec.identity.system_prompt_file}[/cyan]")
    if spec.identity.system_prompt is not None:
        preview = spec.identity.system_prompt[:60].replace("\n", " ")
        identity.add(f"system_prompt: [cyan]{preview}...[/cyan]")

    knowledge = tree.add("[bold]knowledge[/bold]")
    knowledge.add(f"reference_docs_dir: [cyan]{spec.knowledge.reference_docs_dir}[/cyan]")
    knowledge.add(f"include_patterns: {spec.knowledge.include_patterns}")
    knowledge.add(f"exclude_patterns: {spec.knowledge.exclude_patterns}")

    cache = tree.add("[bold]context_cache[/bold]")
    cache.add(f"enabled: {spec.context_cache.enabled}")
    cache.add(f"ttl_seconds: {spec.context_cache.ttl_seconds}")

    memory = tree.add("[bold]memory[/bold]")
    memory.add(f"short_term.buffer_size: {spec.memory.short_term.buffer_size}")
    memory.add(f"long_term.enabled: {spec.memory.long_term.enabled}")
    memory.add(f"long_term.persistence.type: {spec.memory.long_term.persistence.type}")

    grounding = tree.add("[bold]grounding[/bold]")
    grounding.add(f"enabled: {spec.grounding.enabled}")
    grounding.add(f"max_citations: {spec.grounding.max_citations}")

    rate = tree.add("[bold]rate_limit[/bold]")
    rate.add(f"requests_per_minute: {spec.rate_limit.requests_per_minute}")
    rate.add(f"tokens_per_day: {spec.rate_limit.tokens_per_day}")

    console.print(Panel(tree, title="Agent schema", border_style="cyan"))


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


__all__ = [
    "console",
    "print_diff_table",
    "print_error",
    "print_info",
    "print_schema",
    "print_success",
    "print_warning",
]
