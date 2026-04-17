"""Shared Rich helpers used across commands.

The CLI follows the visual identity shared with the author's other open-source
tools (see ``feliperbroering/eai``):

- No emoji characters. Visual cues come from Unicode box-drawing, arrows,
  and restrained accent glyphs (``>``, ``✓``, ``✗``, ``⚠``, ``▶``).
- Success / error / warning lines are prefixed with a single colored glyph,
  not a shouted word in caps. Screen real estate is precious.
- Rich colors are the accent; plain monospace is the norm.
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
    """Render an error line: dim red cross + message."""
    console.print(f"[red]✗[/red] {msg}", highlight=False)


def print_success(msg: str) -> None:
    """Render a success line: green check + message."""
    console.print(f"[green]✓[/green] {msg}", highlight=False)


def print_warning(msg: str) -> None:
    """Render a warning line: yellow warning glyph + message."""
    console.print(f"[yellow]⚠[/yellow] {msg}", highlight=False)


def print_info(msg: str) -> None:
    """Render a neutral informational line prefixed with a subtle chevron."""
    console.print(f"[dim cyan]>[/dim cyan] {msg}", highlight=False)


def print_hint(cmd: str, *, label: str = "try") -> None:
    """Render a cyan-accented hint pointing the user at a command."""
    console.print(f"  [dim]{label}:[/dim] [bold cyan]{cmd}[/bold cyan]", highlight=False)


def print_step(current: int, total: int, msg: str) -> None:
    """Render a numbered step in the classic ``[n/N]`` style."""
    console.print(f"  [dim]\\[{current}/{total}][/dim] {msg}", highlight=False)


def print_kv(label: str, value: str, *, width: int = 12) -> None:
    """Render a dim ``label: value`` pair with consistent column alignment."""
    console.print(f"  [dim]{label:<{width}}[/dim] {value}", highlight=False)


def print_diff_table(diff: dict[str, Any]) -> None:
    """Render a sync diff using a Rich `Table`.

    Expected input::

        {
            "added":   [{"path": "docs/a.md", "sha": "abc1234", "size": 1024}, ...],
            "updated": [...],
            "removed": [{"path": "docs/old.md", "sha": "def4567", "size": 512}, ...],
        }
    """
    table = Table(title="Sync diff", show_lines=False, border_style="dim")
    table.add_column("", width=1, no_wrap=True)
    table.add_column("Path", overflow="fold")
    table.add_column("SHA", no_wrap=True, style="dim")
    table.add_column("Size", justify="right", no_wrap=True, style="dim")

    actions: list[tuple[str, str, str, list[dict[str, Any]]]] = [
        ("+", "green", "added", list(diff.get("added", []) or [])),
        ("~", "yellow", "updated", list(diff.get("updated", []) or [])),
        ("-", "red", "removed", list(diff.get("removed", []) or [])),
    ]
    total = 0
    for glyph, color, _name, entries in actions:
        for entry in entries:
            total += 1
            sha = str(entry.get("sha", ""))[:12]
            size = entry.get("size")
            size_str = _fmt_size(size) if isinstance(size, int) else "-"
            table.add_row(
                f"[{color}]{glyph}[/{color}]",
                str(entry.get("path", "")),
                sha,
                size_str,
            )

    if total == 0:
        console.print("[dim]  no changes — remote is in sync with local[/dim]")
        return
    console.print(table)


def print_schema(schema: AgentSchema) -> None:
    """Render an `AgentSchema` as a Rich `Tree`."""
    meta = schema.metadata
    spec = schema.spec
    tree = Tree(f"[bold]{meta.name}[/bold] [dim]v{meta.version}[/dim]")
    if meta.description:
        tree.add(f"[italic dim]{meta.description}[/italic dim]")

    model = tree.add("[bold]model[/bold]")
    model.add(f"[dim]provider[/dim]  {spec.model.provider}")
    model.add(f"[dim]name[/dim]      {spec.model.name}")
    model.add(f"[dim]temp[/dim]      {spec.model.temperature}")
    model.add(f"[dim]max_out[/dim]   {spec.model.max_output_tokens}")

    identity = tree.add("[bold]identity[/bold]")
    if spec.identity.system_prompt_file is not None:
        identity.add(f"[dim]file[/dim]      {spec.identity.system_prompt_file}")
    if spec.identity.system_prompt is not None:
        preview = spec.identity.system_prompt[:60].replace("\n", " ")
        identity.add(f"[dim]inline[/dim]    {preview}…")

    knowledge = tree.add("[bold]knowledge[/bold]")
    knowledge.add(f"[dim]docs_dir[/dim]  {spec.knowledge.reference_docs_dir}")
    knowledge.add(f"[dim]include[/dim]   {spec.knowledge.include_patterns}")
    knowledge.add(f"[dim]exclude[/dim]   {spec.knowledge.exclude_patterns}")

    cache = tree.add("[bold]context_cache[/bold]")
    cache.add(f"[dim]enabled[/dim]   {spec.context_cache.enabled}")
    cache.add(f"[dim]ttl[/dim]       {spec.context_cache.ttl_seconds}s")

    memory = tree.add("[bold]memory[/bold]")
    memory.add(f"[dim]short_buf[/dim] {spec.memory.short_term.buffer_size}")
    memory.add(f"[dim]long_on[/dim]   {spec.memory.long_term.enabled}")
    memory.add(f"[dim]store[/dim]     {spec.memory.long_term.persistence.type}")

    grounding = tree.add("[bold]grounding[/bold]")
    grounding.add(f"[dim]enabled[/dim]   {spec.grounding.enabled}")
    grounding.add(f"[dim]max_cite[/dim]  {spec.grounding.max_citations}")

    rate = tree.add("[bold]rate_limit[/bold]")
    rate.add(f"[dim]rpm[/dim]       {spec.rate_limit.requests_per_minute}")
    rate.add(f"[dim]tpd[/dim]       {spec.rate_limit.tokens_per_day}")

    console.print(Panel(tree, title="agent schema", border_style="cyan", title_align="left"))


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
    "print_hint",
    "print_info",
    "print_kv",
    "print_schema",
    "print_step",
    "print_success",
    "print_warning",
]
