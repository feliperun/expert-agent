"""`agent-cli init` — scaffold a new agent project directory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

from ..ui import console, print_error, print_info, print_success

_AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")

_SCHEMA_TEMPLATE = """\
apiVersion: expert-agent/v1
kind: AgentSchema
metadata:
  name: {name}
  description: {description!r}
  version: "0.1.0"
spec:
  model:
    provider: gemini
    name: gemini-3.1-pro
    temperature: 0.3
    max_output_tokens: 8192
    top_p: 0.95
  identity:
    system_prompt_file: ./prompts/identity.md
  knowledge:
    reference_docs_dir: ./docs
    include_patterns:
      - "*.md"
      - "*.pdf"
      - "*.txt"
    exclude_patterns:
      - "_drafts/*"
  context_cache:
    enabled: true
    ttl_seconds: 3600
    refresh_before_expiry_seconds: 300
  memory:
    short_term:
      buffer_size: 20
      storage: firestore
    long_term:
      enabled: true
      engine: mempalace
      max_recall_results: 5
      persistence:
        type: chroma-http
  grounding:
    enabled: true
    max_citations: 10
  rate_limit:
    requests_per_minute: 30
    tokens_per_day: 1000000
"""

_IDENTITY_TEMPLATE = """\
# Identity — {title}

You are an ultra-specialist assistant in [YOUR DOMAIN]. Your knowledge is based
**exclusively** on the reference documents loaded in your context. You never
invent facts outside of these sources.

## Response Rules

1. **Cite sources.** For every factual claim, cite the source document and section.
2. **Disclaim uncertainty.** If the documents do not cover a question, say so explicitly.
3. **Be precise.** Prefer exact values, formulas, and quotations over paraphrases.
4. **Stay in domain.** If asked about something outside your domain, politely redirect.

## Language

Respond in the language the user writes to you.
"""

_README_TEMPLATE = """\
# {name}

An ultra-specialist agent scaffolded with `agent-cli init`.

## Layout

- `agent_schema.yaml` — declarative agent configuration.
- `prompts/identity.md` — system prompt (referenced from the schema).
- `docs/` — reference documents loaded into the long context window.

## Next steps

1. Drop your domain documents (`*.md`, `*.pdf`, `*.txt`) under `docs/`.
2. Edit `prompts/identity.md` to describe the agent's persona and rules.
3. Validate locally:

   ```sh
   agent-cli validate --schema ./agent_schema.yaml
   ```

4. Estimate token usage to size the Context Cache:

   ```sh
   agent-cli count-tokens --schema ./agent_schema.yaml
   ```

5. Deploy and then sync the documents to the running agent:

   ```sh
   agent-cli sync --schema ./agent_schema.yaml
   ```
"""


def _prompt_name(default: str) -> str:
    while True:
        value: str = typer.prompt("Agent name", default=default)
        value = value.strip()
        if not _AGENT_NAME_RE.match(value):
            print_error(
                "name must match ^[a-z][a-z0-9-]*$ (lowercase letters, digits, hyphens)."
            )
            continue
        if len(value) > 63:
            print_error("name must be at most 63 characters (Cloud Run service name limit).")
            continue
        return value


def cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Destination directory for the new agent."),
    ] = Path("./my-agent"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite files if the destination already exists."),
    ] = False,
) -> None:
    """Scaffold a new agent project at `PATH`."""
    default_name = path.name or "my-agent"
    if not _AGENT_NAME_RE.match(default_name):
        default_name = "my-agent"

    name = _prompt_name(default_name)
    description: str = typer.prompt(
        "Description",
        default=f"Ultra-specialist agent '{name}'.",
    ).strip()

    path = path.resolve()
    schema_file = path / "agent_schema.yaml"
    identity_file = path / "prompts" / "identity.md"
    docs_keep = path / "docs" / ".gitkeep"
    readme_file = path / "README.md"

    existing = [p for p in (schema_file, identity_file, docs_keep, readme_file) if p.exists()]
    if existing and not force:
        print_error(
            f"destination {path} already contains: "
            + ", ".join(str(p.relative_to(path)) for p in existing)
            + " — pass --force to overwrite.",
        )
        raise typer.Exit(code=1)

    try:
        (path / "prompts").mkdir(parents=True, exist_ok=True)
        (path / "docs").mkdir(parents=True, exist_ok=True)
        schema_file.write_text(
            _SCHEMA_TEMPLATE.format(name=name, description=description),
            encoding="utf-8",
        )
        identity_file.write_text(
            _IDENTITY_TEMPLATE.format(title=name.replace("-", " ").title()),
            encoding="utf-8",
        )
        docs_keep.write_text("", encoding="utf-8")
        readme_file.write_text(_README_TEMPLATE.format(name=name), encoding="utf-8")
    except OSError as exc:
        print_error(f"failed to write files: {exc}")
        raise typer.Exit(code=1) from exc

    print_success(f"Created new agent at [cyan]{path}[/cyan].")
    print_info("Next step: [bold]agent-cli validate --schema ./agent_schema.yaml[/bold]")
    console.print()
