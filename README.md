<div align="center">

```
 ███████╗██╗  ██╗██████╗ ███████╗██████╗ ████████╗         
 ██╔════╝╚██╗██╔╝██╔══██╗██╔════╝██╔══██╗╚══██╔══╝  ╭───╮  
 █████╗   ╚███╔╝ ██████╔╝█████╗  ██████╔╝   ██║     │ ≡ │  
 ██╔══╝   ██╔██╗ ██╔═══╝ ██╔══╝  ██╔══██╗   ██║     ╰───╯  
 ███████╗██╔╝ ██╗██║     ███████╗██║  ██║   ██║            
 ╚══════╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝   ╚═╝            
```

**ground a model on your docs. ship it as an API.**

declarative ultra-specialist agents on Cloud Run — Gemini long-context, Context Cache, persistent memory.

[![CI](https://github.com/feliperbroering/expert-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/feliperbroering/expert-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)](#status)

</div>

---

```bash
# 1. scaffold an agent
expert init cardio-expert

# 2. drop your corpus
cp ~/papers/*.pdf cardio-expert/docs/

# 3. validate + size the context cache
expert validate && expert count-tokens

# 4. deploy once, ask forever
expert sync && expert ask "qual fórmula de correção do QTc a AHA recomenda?"
```

You define the agent declaratively — a system prompt, a directory of reference documents, and a YAML schema. `expert-agent` gives you back a deployable API with grounded answers, citations, long-term memory, and LGPD-friendly session controls.

> [!NOTE]
> **Status — alpha.** End-to-end production deploy validated on Google Cloud Run (FastAPI + Chroma HTTP + Firestore + GCS). API surface and schema are still subject to breaking changes until `v1.0`.

---

## What you get

Out of the box, your deployed agent exposes:

- **`POST /ask`** — streaming Q&A grounded in your corpus, with optional citations
- **`POST /docs/sync`** — incremental upload of the knowledge base (SHA-keyed)
- **`GET/DELETE /sessions/...`** — short-term conversational memory (LGPD/GDPR)
- **`POST /memory/...`** — long-term verbatim recall (not summaries)
- **`GET /health` / `/ready`** — liveness + dependency probes

A Python CLI (`expert`) handles scaffolding, validation, sync, ad-hoc queries, multi-agent workspace management, and a ready-to-run Robot Framework E2E kit.

---

## Quick start

### Install

```bash
# uv (recommended — single static binary experience)
uv tool install "git+https://github.com/feliperbroering/expert-agent.git"

# or pipx
pipx install "git+https://github.com/feliperbroering/expert-agent.git"
```

Verify:

```bash
expert --version
```

### Scaffold your first agent

```bash
expert init my-expert
cd my-expert
$EDITOR prompts/identity.md         # define behaviour
cp ~/your-corpus/*.pdf docs/        # drop in your reference material
expert validate                     # schema contract check
expert count-tokens                 # size the context cache
```

### Deploy to Google Cloud

One-time project bootstrap:

```bash
PROJECT_ID=my-agents-prod REGION=us-central1
gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT_ID"

./scripts/bootstrap-project.sh "$PROJECT_ID" "$REGION"

echo -n "YOUR_GEMINI_KEY" | \
  gcloud secrets versions add gemini-api-key --data-file=- --project="$PROJECT_ID"
```

Apply the shared infra (runs per project, not per agent):

```bash
(cd infra/platform && tofu init -backend-config="bucket=${PROJECT_ID}-tfstate" && tofu apply -var="project_id=${PROJECT_ID}" -var="region=${REGION}")
(cd infra/chroma   && tofu init -backend-config="bucket=${PROJECT_ID}-tfstate" && tofu apply -var="project_id=${PROJECT_ID}" -var="region=${REGION}")
```

Build + ship the backend image:

```bash
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions=_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/expert-agent/backend:v0.1.0"
```

Provision this agent's Cloud Run service:

```bash
cd ../infra/agent
tofu init -reconfigure \
  -backend-config="bucket=${PROJECT_ID}-tfstate" \
  -backend-config="prefix=agent/my-expert"
tofu apply \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="agent_id=my-expert" \
  -var="image=${REGION}-docker.pkg.dev/${PROJECT_ID}/expert-agent/backend:v0.1.0"
```

Seed the admin key, push docs, ask:

```bash
ADMIN_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
echo -n "$ADMIN_KEY" | \
  gcloud secrets versions add admin-key-my-expert --data-file=- --project="${PROJECT_ID}"

expert sync \
  --endpoint "$(gcloud run services describe agent-my-expert --region="${REGION}" --format='value(status.url)')" \
  --api-key "$ADMIN_KEY"

expert ask "what does my corpus say about X?" --api-key "$ADMIN_KEY"
```

See [`docs/PRIVATE_AGENT_REPO.md`](./docs/PRIVATE_AGENT_REPO.md) for the full private-repo checklist (one agent) and [`infra/README.md`](./infra/README.md) for the per-stack reference.

---

## Multi-agent workspaces

A single repo can host many agents. `expert` auto-detects them and offers three equivalent ways to pick which one a command targets:

```bash
expert agents                           # list everything the workspace knows about

# pick per-invocation
expert ask --agent derm "..."           # explicit flag
expert @derm ask "..."                  # @alias positional shortcut
EXPERT_AGENT=derm expert ask "..."      # env var

# pin for a session
expert use derm                         # write .expert/state.json
expert ask "..."                        # uses derm from now on
expert which                            # which agent would run?
```

Declare agents explicitly via `expert.toml` for full control:

```toml
default_agent = "derm"

[agents.derm]
schema = "derm-expert/agent_schema.yaml"
endpoint_env = "DERM_AGENT_ENDPOINT"
api_key_env = "DERM_AGENT_API_KEY"

[agents.my-expert]
schema = "my-expert/agent_schema.yaml"
endpoint_env = "MY_EXPERT_ENDPOINT"
api_key_env = "MY_EXPERT_API_KEY"
```

…or skip the file entirely — any sibling directory with an `agent_schema.yaml` is discovered automatically.

**Resolution precedence** (first match wins): `--agent` flag → `@alias` → `EXPERT_AGENT` env var → `expert use` pin → `expert.toml` default → single-agent short-circuit.

---

## Defining an agent

Minimal `agent_schema.yaml`:

```yaml
apiVersion: expert-agent/v1
kind: AgentSchema
metadata:
  name: my-expert
  description: "What this agent specialises in (one sentence)."
  version: "0.1.0"

spec:
  model:
    provider: gemini                    # or `gemini-vertex`
    name: gemini-2.5-pro                # any tier with Context Caching
    temperature: 0.2
    max_output_tokens: 8192

  identity:
    system_prompt_file: ./prompts/identity.md   # or inline `system_prompt: "..."`

  knowledge:
    reference_docs_dir: ./docs
    include_patterns: ["*.md", "*.pdf", "*.txt"]
    exclude_patterns: ["_drafts/*"]

  context_cache:
    enabled: true
    ttl_seconds: 3600                   # 1 h — the AI Studio sweet spot
    refresh_before_expiry_seconds: 300

  memory:
    short_term: { buffer_size: 20, storage: firestore }
    long_term:  { enabled: true, engine: mempalace, max_recall_results: 5,
                  persistence: { type: chroma-http } }

  grounding:
    enabled: false                      # AI Studio rejects `tools=GoogleSearch` + `cachedContent`
    max_citations: 10

  rate_limit: { requests_per_minute: 30, tokens_per_day: 1000000 }
```

Full annotated example: [`example-schema/`](./example-schema/).

---

## CLI reference

```text
expert init <name>                  scaffold a new agent project
expert agents                       list agents in this workspace
expert use <name>                   pin an agent as active
expert which                        show which agent a bare command targets
expert validate                     validate agent_schema.yaml
expert count-tokens                 estimate corpus tokens (cache budgeting)
expert sync                         push docs + rebuild Context Cache
expert ask "<question>"             stream answer from the deployed agent
expert sessions list/show/delete    manage user sessions (LGPD)
expert test                         run the packaged Robot Framework E2E kit
expert --version                    show the brand + version
```

Every command supports `--help`, `--agent <name>` (or `@alias`), `--endpoint`, `--api-key`.

---

## End-to-end testing

A ready-made Robot Framework kit ships with the CLI. Install with the `[test]` extra:

```bash
uv tool install 'expert-agent[test] @ git+https://github.com/feliperbroering/expert-agent.git'
export EXPERT_AGENT_ENDPOINT=https://my-agent-xxxx.a.run.app
export EXPERT_AGENT_API_KEY=$(gcloud secrets versions access latest --secret=admin-key-my-expert)

expert test                         # all suites
expert test --suite 05_ask_latency  # single suite
expert test --list                  # discover suites
```

Suites shipped:

| Suite             | Offline? | Asserts                                                 |
|-------------------|:--------:|---------------------------------------------------------|
| `01_validate`     | yes      | `expert validate` succeeds on the agent schema          |
| `02_create`       | yes      | `expert init --yes` scaffolds + validates out of the box|
| `03_update`       | yes      | edit → validate loop preserves schema integrity         |
| `04_deploy`       | no       | `/health`, `/ready` respond 200; unauth calls get 401   |
| `05_ask_latency`  | no       | warmup + steady-state TTFT budgets + cache-hit signal   |
| `06_sessions`     | no       | LGPD: create → list → delete round-trip                 |

### Reusable GitHub Actions workflow

Private agent repos inherit the same suites via a reusable workflow — no submodules, no copy-paste. See [`.github/workflows/expert-e2e.yml`](.github/workflows/expert-e2e.yml):

```yaml
jobs:
  e2e:
    uses: feliperbroering/expert-agent/.github/workflows/expert-e2e.yml@main
    with:
      schema: my-expert/agent_schema.yaml
      suite: 05_ask_latency               # optional — omit to run everything
    secrets:
      endpoint: ${{ secrets.EXPERT_AGENT_ENDPOINT }}
      api-key:  ${{ secrets.EXPERT_AGENT_API_KEY }}
```

For monorepos hosting multiple agents, use a matrix strategy (see [`docs/AGENT_E2E_SETUP.md`](docs/AGENT_E2E_SETUP.md)).

---

## Architecture

```
   client (CLI / HTTP)
          │
          ▼
   ┌──────────────────────────────┐
   │  agent  (Cloud Run, FastAPI) │ ◀── reads agent_schema.yaml
   │  ├─ /ask         (SSE)       │     from gs://docs-bucket/<agent>/schema/
   │  ├─ /docs/sync               │
   │  ├─ /sessions /memory        │
   │  └─ /health /ready           │
   └────┬───────────┬─────────┬───┘
        │           │         │
        ▼           ▼         ▼
   Gemini API   Firestore   Chroma HTTP (Cloud Run, min=1)
   (Context     (sessions   ├─ shared per project
    Cache)       + state)   └─ persisted via GCS FUSE → gs://memory/chroma
        ▲
        │ File API mirror
        │
   GCS (durable source of truth)
   ├─ gs://docs/<agent>/<sha>/<file>          knowledge base
   ├─ gs://docs/<agent>/_state/sync_manifest.json
   ├─ gs://docs/<agent>/schema/...            schema + prompts
   └─ gs://memory/<agent>/                    long-term memory snapshots
```

**Key design choices** ([deeper notes in `infra/README.md`](./infra/README.md)):

- **Stateless agent containers.** All state lives in GCS or Firestore. Cloud Run can scale to zero and back without losing context.
- **Context Cache as the grounding source.** Documents go into a Gemini Context Cache built once per knowledge-base SHA; subsequent `/ask` calls reuse it (`cached_tokens ≈ input_tokens` in steady state).
- **Multi-layer memory.** Firestore holds the last N turns (short-term) plus a verbatim recall index (long-term, indexed in Chroma via [MemPalace](https://pypi.org/project/mempalace/)).
- **One Chroma HTTP server per project** (Cloud Run, `min=max=1`, GCS FUSE for persistence) — shared across every agent in the project.

---

## vs other ways to ship a RAG agent

|                                         | expert-agent             | NotebookLM         | OpenAI Assistants        | Bring-your-own RAG stack |
|-----------------------------------------|:------------------------:|:------------------:|:------------------------:|:------------------------:|
| **API you own**                         | ✓ (your Cloud Run)       | ✗ (Google UI only) | ✓ (OpenAI hosted)        | ✓                        |
| **Grounded in your corpus**             | ✓ (Context Cache)        | ✓                  | ✓ (file_search)          | ✓ (you wire it up)       |
| **Long-context native** (100k+ tokens)  | ✓ (Gemini 2.5 Pro)       | ✓                  | partial (chunked)        | depends                  |
| **Declarative YAML spec**               | ✓ (`agent_schema.yaml`)  | ✗                  | ✗                        | ✗                        |
| **Multi-agent in one repo**             | ✓ (`expert.toml` + `@`)  | n/a                | ✗                        | DIY                      |
| **Persistent conversation memory**      | ✓ (Firestore + MemPalace)| partial            | ✓                        | DIY                      |
| **E2E test kit** (Robot Framework)      | ✓ (reusable workflow)    | ✗                  | ✗                        | DIY                      |
| **LGPD/GDPR session delete**            | ✓ (`/sessions/:id`)      | ✗                  | partial                  | DIY                      |
| **Self-hosted**                         | ✓ (your GCP project)     | ✗                  | ✗                        | ✓                        |
| **Open source**                         | ✓ (MIT)                  | ✗                  | ✗                        | varies                   |

---

## Authentication

Cloud Run uses **two layers of bearer auth**, intentionally:

| Header                          | Audience                  | Required for                   |
|---------------------------------|---------------------------|--------------------------------|
| `X-Serverless-Authorization`    | Cloud Run IAM (ID token)  | reaching the service at all    |
| `Authorization: Bearer <KEY>`   | App layer (admin key)     | `/ask`, `/docs/sync`, `/memory`|

The split avoids the well-known collision where Cloud Run's IAM strips `Authorization` before the app sees it. Public endpoints (`/health`, `/ready`) only need the ID token. For local dev, set `APP_ENV=development` to skip the admin-key check (see `backend/app/auth.py`).

---

## Repository layout

```
backend/            FastAPI app (`app.main:app`) + tests
  app/llm/          LLMClient protocol + Gemini AI Studio / Vertex implementations
  app/cache/        Context Cache manager + background refresher
  app/docs/         Manifest + DocsSyncService (incremental SHA diff)
  app/memory/       Short-term (Firestore) + long-term (MemPalace/Chroma) + orchestrator
  app/routes/       /ask /docs/sync /sessions /memory /health
cli/                `expert` CLI (Typer + Rich) + Robot Framework testkit
example-schema/     annotated AgentSchema + prompt template
infra/              OpenTofu stacks: platform, chroma, agent (per agent)
scripts/            bootstrap-project.sh, bootstrap_docs_to_gcs.py
docs/               PRIVATE_AGENT_REPO.md, AGENT_E2E_SETUP.md
.github/workflows/  ci.yml, release-please.yml, deploy.yml, expert-e2e.yml
```

---

## Cost ballpark

For a single project hosting one or more agents on `us-central1`, idling on Cloud Run scale-to-zero:

| Component                            | Idle           | Notes                                  |
|--------------------------------------|----------------|----------------------------------------|
| Chroma server (Cloud Run, min=max=1) | **~$40 / mo**  | always-on, shared across all agents    |
| Each agent (Cloud Run, min=0)        | **~$0**        | pay only on request                    |
| Firestore                            | **~$0**        | free tier covers low-QPS use           |
| Gemini Pro requests                  | **variable**   | `cached_tokens` are heavily discounted |
| GCS storage                          | **~$0.02/GiB** | docs + memory snapshots                |

Headline efficiency win: with Context Caching on, a typical `/ask` against a ~800 k-token corpus shows `cached_tokens / input_tokens ≈ 0.999` — the prompt portion of the cost is essentially flat regardless of how big your corpus is.

---

## Roadmap

- [ ] Vertex AI client tested at parity with AI Studio (grounding + cache).
- [ ] Built-in evaluation harness (`expert eval` against gold Q&A pairs).
- [ ] OpenTelemetry export wired into Cloud Trace by default.
- [ ] Multi-tenant agent (per-tenant memory + cache) for SaaS use cases.
- [ ] Web UI / playground for non-technical curators.
- [ ] `release-please`-driven versioned container tags pushed to GHCR.
- [ ] PyPI release (`pip install expert-agent`) + Homebrew tap.

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md) for dev setup, style, and conventions. AI coding agents: read [AGENTS.md](./AGENTS.md) first. Please report security issues privately via [SECURITY.md](./SECURITY.md). We follow the [Contributor Covenant v2.1](./CODE_OF_CONDUCT.md).

```bash
uv sync --extra dev --extra vertex --extra otel
uv run ruff check .
uv run mypy backend cli
uv run pytest
```

---

## Acknowledgements

`expert-agent` stands on the shoulders of giants: [Gemini](https://ai.google.dev/), [FastAPI](https://fastapi.tiangolo.com/), [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/), [Chroma](https://www.trychroma.com/), [MemPalace](https://pypi.org/project/mempalace/), [Robot Framework](https://robotframework.org/), [OpenTofu](https://opentofu.org/).

---

## License

[MIT](./LICENSE) — do what you want, just don't sue us.
