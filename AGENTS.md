# AGENTS.md — contract for AI contributors

This document is the short version of [CONTRIBUTING.md](./CONTRIBUTING.md) tuned for AI coding agents (Cursor, Claude Code, Codex, Aider, Cline, Continue, and friends). Reading this in full before proposing changes will save you a round of review.

---

## Project mental model

`expert-agent` is a framework for shipping **ultra-specialist AI agents** — declarative YAML spec + corpus of reference docs → deployable API on Google Cloud Run. Three layers:

1. **`backend/`** — FastAPI app (`app.main:app`). Stateless containers. State lives in GCS + Firestore + Chroma.
2. **`cli/`** — `expert` (Typer + Rich). Scaffold, validate, sync, ask, manage sessions, run E2E tests. **Workspace-aware** (multi-agent via `expert.toml`).
3. **`infra/`** — OpenTofu stacks (platform, chroma, agent). Per-project shared infra + per-agent Cloud Run service.

Ground rule: **the backend is stateless**. Every new feature must survive `min=0` scale-to-zero. If you need state, put it in GCS or Firestore.

---

## Non-negotiables

- **No emoji in source code.** Ever. Use `rich` colors and Unicode box-drawing. See `cli/expert/ui.py` + `cli/expert/brand.py` for the visual identity.
- **Type hints everywhere.** `mypy --strict` must stay green on `backend/` and `cli/`.
- **Lint + format must pass.** `ruff check .` + `ruff format .`.
- **Tests must pass.** `pytest` green locally *and* in CI. Add tests for every behaviour change.
- **Conventional Commits.** `feat(scope): ...`, `fix(scope): ...`, etc. Release-please reads these.
- **No breaking API changes on `main`** without a migration note in the PR description.

---

## Where to put things

| Change                                              | Goes in                                                                     |
|-----------------------------------------------------|-----------------------------------------------------------------------------|
| New CLI command                                     | `cli/expert/commands/<name>.py` + register in `cli/expert/main.py`          |
| New backend endpoint                                | `backend/app/routes/<name>.py` + mount in `backend/app/main.py`             |
| New schema field                                    | `backend/app/schema.py` (pydantic) + update `example-schema/` sample        |
| New UI helper                                       | `cli/expert/ui.py` (follow the existing API shape: `print_*`)               |
| New infra resource                                  | Right `infra/<stack>/` — `platform` (shared), `chroma` (shared), `agent` (per-agent) |
| New E2E test                                        | `cli/expert/testkit/suites/NN_<name>.robot` + keywords in `.resource`       |
| New multi-agent resolution rule                     | `cli/expert/workspace.py::Workspace.resolve` (document the precedence!)     |

---

## The visual identity

The brand wordmark + tagline live in `cli/expert/brand.py`. Do **not** touch the ASCII art without approval — it's shared with the author's other open-source CLIs (`feliperbroering/eai`) and exists to create a coherent family look.

UI conventions for any user-facing text:

```text
✓ success              → print_success("message")
✗ error                → print_error("message")
⚠ warning              → print_warning("message")
› neutral info         → print_info("message")
▶ streamed output      → reserved for assistant output in `expert ask`
```

Never invent new glyphs without updating `cli/expert/ui.py` and its docstring.

---

## Before opening a PR

Run this locally. It's what CI runs. If any line fails, fix it before pushing:

```bash
source .venv/bin/activate
uv run ruff check . && uv run ruff format .
uv run mypy backend cli
uv run pytest -q
```

### Writing good CLI tests

- Use `typer.testing.CliRunner()` (see `cli/tests/test_main_alias.py` for the canonical pattern).
- **Don't pin on glyphs.** Assert on stable strings like `"name must match"` — the `✗` prefix is a skin, not an API.
- For workspace tests, build minimal `expert.toml` + `agent_schema.yaml` in `tmp_path`.

### Writing good backend tests

- Use `pytest-asyncio` (auto mode) + `respx` for HTTP stubbing.
- Firestore is mocked via `mock-firestore`. Do not hit real Google APIs in tests.
- Every new `/route` gets at least: auth test, happy path, one error path.

---

## Things that will get your PR rejected

- Adding a dependency without justifying it in the PR description.
- Introducing state outside GCS / Firestore / Chroma (e.g. in-memory caches that assume a single replica).
- Silencing `mypy` with `# type: ignore` without a comment explaining why.
- Reformatting unrelated code.
- Commits that are not Conventional Commits.
- Breaking `ruff` (lint *or* format) without documented reason.
- Copying the ASCII brand into other files — it's re-exported from `cli/expert/brand.py` precisely so we change it in one place.

---

## Multi-agent workspaces — the part you'll probably touch

A single repo can host many agents. Resolution precedence (first match wins):

1. `--agent <name>` flag
2. `@<alias>` positional shortcut (rewritten to `--agent` by `_rewrite_at_alias` in `main.py`)
3. `EXPERT_AGENT` env var
4. `expert use <name>` pin (written to `.expert/state.json`)
5. `default_agent` in `expert.toml`
6. Single-agent short-circuit (workspace has exactly one agent)
7. `--schema <path>` overrides everything (legacy bypass for `expert validate` etc.)

If you add a new command that needs to target an agent:

```python
from ..context import resolve_context

def cmd(
    agent: Annotated[str | None, typer.Option("--agent", "-a", ...)] = None,
    # other flags
) -> None:
    ctx = resolve_context(selector=agent, ...)
    # ctx.name, ctx.schema_path, ctx.endpoint, ctx.api_key are all filled in
```

Don't roll your own resolution logic.

---

## License

By contributing, you agree your work is released under the [MIT License](./LICENSE). The CLA is: **open a PR, you've agreed**. Nothing to sign.

---

## When in doubt

Open a draft PR or file an issue. Showing intent beats writing the wrong thing twice.
