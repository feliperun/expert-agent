# Contributing to expert-agent

Thanks for taking the time to contribute. This project is MIT-licensed and run in public — every patch, typo fix, and review comment is genuinely welcome.

If you're an AI coding agent (Cursor, Claude Code, Codex, Aider, etc.) **read [AGENTS.md](./AGENTS.md) first** — it's the short version of this document tuned for AI collaborators.

---

## Before you open a PR

1. **Check the open issues and PRs** for duplicates. If something is already in flight, ping there instead of forking a parallel effort.
2. **For non-trivial changes, open an issue first.** A two-line "I'd like to implement X, is it welcome?" saves everyone time.
3. **Keep PRs focused.** One feature or one fix per PR. Refactors are welcome but ship them separately from behaviour changes.

---

## Local setup

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and (optionally) Docker + OpenTofu if you're touching infra.

```bash
git clone https://github.com/feliperbroering/expert-agent
cd expert-agent

uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev,test,vertex,otel]"

# quick smoke test
expert --version
expert --help
```

---

## Checks that must pass

The CI runs exactly these three commands. Run them locally before pushing:

```bash
uv run ruff check .            # lint — use `--fix` for auto-fixes
uv run ruff format .           # formatter
uv run mypy backend cli        # strict type checks
uv run pytest                  # unit + integration tests
```

Target coverage: **85%+** on backend, **90%+** on CLI. New code must include tests.

### End-to-end

If you're changing user-facing CLI behaviour or the HTTP contract, run the Robot Framework suite against a local or staging agent:

```bash
expert test --suite 01_validate       # offline suites, no endpoint needed
expert test --endpoint http://... --api-key ... --suite 04_deploy
```

---

## Code style

- **No emoji in source code.** Visual cues come from `rich` colors and Unicode box-drawing (see `cli/expert/ui.py`).
- **Docstrings over comments.** Functions and classes get docstrings; inline comments only explain *why*, not *what*.
- **Type hints everywhere.** `mypy --strict` is non-negotiable on the backend and CLI.
- **Prefer explicit over clever.** The project is a library people read; optimise for clarity.
- **Conventional Commits.** Every commit subject follows [`<type>(<scope>): <message>`](https://www.conventionalcommits.org/). Allowed types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `style`, `perf`, `build`, `ci`.

Releases are automated — [release-please](https://github.com/googleapis/release-please) reads Conventional Commits on `main` and opens version-bump PRs.

---

## What lives where

```
backend/app/        FastAPI app code
backend/tests/      backend unit + integration tests
cli/expert/         the `expert` Typer app
cli/expert/testkit/ Robot Framework suites shipped inside the wheel
cli/tests/          CLI unit tests
example-schema/     annotated sample AgentSchema + identity.md
infra/              OpenTofu stacks (platform / chroma / agent)
scripts/            one-off bootstrap + migration scripts
docs/               PRIVATE_AGENT_REPO, AGENT_E2E_SETUP
.github/workflows/  ci, release-please, deploy, expert-e2e (reusable)
```

When you touch one layer, stay in it. Cross-cutting refactors (e.g. renaming a pydantic field used by backend + CLI) are fine but should update *both* in the same PR.

---

## Tests in the CLI — important patterns

- Use `typer.testing.CliRunner()` for integration tests (see `cli/tests/test_main_alias.py`).
- Avoid asserting on colored/glyph-decorated output text — pin to the **stable** part of the message (e.g. `"name must match"` instead of the `✗` glyph). See `cli/tests/test_init.py` for the pattern.
- For workspace-dependent tests, use the `tmp_path` fixture and build minimal `expert.toml` / `agent_schema.yaml` files inline.

---

## Filing a good bug report

Please include:

- `expert --version`
- Python version (`python --version`)
- Minimal reproducer (schema + command + expected vs actual)
- Relevant traceback, trimmed
- OS

A template is provided at [`.github/ISSUE_TEMPLATE/bug_report.yml`](./.github/ISSUE_TEMPLATE/bug_report.yml).

---

## Filing a good feature request

Please describe:

- The problem (user story) — *"as a curator of X, I want to Y so that Z"*
- The shape of the solution you'd expect (CLI flag? new schema field? new endpoint?)
- Alternatives you considered

A template is provided at [`.github/ISSUE_TEMPLATE/feature_request.yml`](./.github/ISSUE_TEMPLATE/feature_request.yml).

---

## Security

If you think you've found a vulnerability, **do not open a public issue.** Follow the private disclosure process in [SECURITY.md](./SECURITY.md).

---

## Code of Conduct

Participation in this project is governed by the [Contributor Covenant v2.1](./CODE_OF_CONDUCT.md). In short: be kind, assume good faith, and don't make it weird.

---

## License

By contributing, you agree that your contribution is licensed under the [MIT License](./LICENSE).
