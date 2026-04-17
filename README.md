# expert-agent

> **NotebookLM as an API.** Open-source framework for ultra-specialist AI agents
> grounded in a curated knowledge base, powered by Gemini long-context + Context
> Caching, with multi-layer persistent memory.

[![CI](https://github.com/feliperbroering/expert-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/feliperbroering/expert-agent/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](./LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)

> **Status — alpha.** End-to-end production deploy validated on Google Cloud
> Run (FastAPI backend + Chroma HTTP + Firestore + GCS). API surface and
> schema are still subject to breaking changes until `v1.0`.

---

## What you get

You define an agent declaratively:

1. A **system prompt** (the agent's identity and behaviour).
2. A **directory of reference documents** (`.md`, `.pdf`, `.txt`).
3. A **YAML schema** (`agent_schema.yaml`) wiring the two together.

…and `expert-agent` gives you a deployable Cloud Run service exposing:

- **`/ask`** — streaming Q&A grounded in the corpus, with optional citations.
- **`/docs/sync`** — incremental upload of the knowledge base (SHA-keyed).
- **`/sessions/...`** — short-term conversational memory (LGPD/GDPR friendly).
- **`/memory/...`** — long-term semantic recall (verbatim, not summarised).
- **`/health`** + **`/ready`** — liveness + dependency probes.

A Python CLI (`expert`) handles scaffolding, validation, sync, and
ad-hoc queries against any deployed agent.

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

- **Stateless agent containers.** All state lives in GCS or Firestore. Cloud
  Run can scale to zero and back without losing context.
- **Context Cache as the grounding source.** Documents go into a Gemini
  Context Cache built once per knowledge-base SHA; subsequent `/ask` calls
  reuse it (`cached_tokens ≈ input_tokens` in steady state).
- **Multi-layer memory.** Firestore holds the last N turns of conversation
  (short-term) plus a verbatim recall index (long-term, indexed in Chroma
  via [MemPalace](https://pypi.org/project/mempalace/)).
- **One Chroma HTTP server per project** (Cloud Run, `min=max=1`, GCS FUSE
  for persistence) — shared across every agent in the project.

---

## Quick start

### 1. Bootstrap a GCP project (one-time)

```bash
PROJECT_ID=my-agents-prod
REGION=us-central1

gcloud auth login
gcloud auth application-default login
gcloud config set project "$PROJECT_ID"

# Enables APIs, creates tfstate bucket, Artifact Registry, Firestore,
# and the empty `gemini-api-key` secret. Idempotent.
./scripts/bootstrap-project.sh "$PROJECT_ID" "$REGION"

# Inject your Gemini API key (get one at https://aistudio.google.com/apikey).
echo -n "YOUR_GEMINI_KEY" | \
  gcloud secrets versions add gemini-api-key --data-file=- --project="$PROJECT_ID"
```

### 2. Apply the shared platform stacks

```bash
cd infra/platform
tofu init -backend-config="bucket=${PROJECT_ID}-tfstate"
tofu apply -var="project_id=${PROJECT_ID}" -var="region=${REGION}"
cd ../chroma
tofu init -backend-config="bucket=${PROJECT_ID}-tfstate"
tofu apply -var="project_id=${PROJECT_ID}" -var="region=${REGION}"
```

### 3. Build & push the backend image

```bash
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions=_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/expert-agent/backend:v0.1.0"
```

### 4. Scaffold and deploy your first agent

```bash
# Install the CLI (uv tool style — single root pyproject.toml)
uv tool install "git+https://github.com/feliperbroering/expert-agent.git"

# Scaffold an agent locally
expert init my-expert
cd my-expert
$EDITOR prompts/identity.md            # define behaviour
cp ~/papers/*.pdf docs/                # drop in your corpus
expert validate --schema ./agent_schema.yaml

# Provision Cloud Run + IAM + secrets for this agent
cd ../infra/agent
tofu init -reconfigure \
  -backend-config="bucket=${PROJECT_ID}-tfstate" \
  -backend-config="prefix=agent/my-expert"
tofu apply \
  -var="project_id=${PROJECT_ID}" \
  -var="region=${REGION}" \
  -var="agent_id=my-expert" \
  -var="image=${REGION}-docker.pkg.dev/${PROJECT_ID}/expert-agent/backend:v0.1.0"

# Seed the per-agent admin key (one-time)
ADMIN_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
echo -n "$ADMIN_KEY" | \
  gcloud secrets versions add admin-key-my-expert --data-file=- --project="${PROJECT_ID}"

# Push docs + create the Context Cache
expert sync \
  --schema ./agent_schema.yaml \
  --endpoint "$(gcloud run services describe agent-my-expert \
                  --region="${REGION}" --format='value(status.url)')" \
  --api-key "$ADMIN_KEY"

# Ask something
expert ask "What does my corpus say about X?" \
  --endpoint <SERVICE_URL> --api-key "$ADMIN_KEY"
```

> See [`infra/README.md`](./infra/README.md) for the full per-stack reference.

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
    provider: gemini             # or `gemini-vertex` (optional `[vertex]` extra)
    name: gemini-2.5-pro          # any Pro tier with Context Caching support
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
    ttl_seconds: 3600                  # 1 h is the AI Studio sweet spot
    refresh_before_expiry_seconds: 300

  memory:
    short_term: { buffer_size: 20, storage: firestore }
    long_term:  { enabled: true, engine: mempalace, max_recall_results: 5,
                  persistence: { type: chroma-http } }

  grounding:
    # AI Studio rejects `tools=GoogleSearch` together with `cachedContent`.
    # Vertex supports both — flip this on if you migrate.
    enabled: false
    max_citations: 10

  rate_limit: { requests_per_minute: 30, tokens_per_day: 1000000 }
```

A full annotated example lives in [`example-schema/`](./example-schema/).

---

## CLI reference

```text
expert init <name>           Scaffold a new agent project
expert validate              Validate agent_schema.yaml against the contract
expert count-tokens          Estimate corpus tokens (Context Cache budgeting)
expert sync                  Push docs + rebuild Context Cache
expert ask "<question>"      Stream answer from a deployed agent
expert sessions list/delete  Manage user sessions (LGPD)
expert test                  Run the packaged E2E Robot Framework kit
```

Every command supports `--help` for full options.

---

## End-to-end testing

A ready-made Robot Framework kit ships with the CLI. Install with the
`[test]` extra and run against any agent:

```bash
uv tool install 'expert-agent[test] @ git+https://github.com/feliperbroering/expert-agent.git'
export EXPERT_AGENT_ENDPOINT=https://my-agent-xxxx.a.run.app
export EXPERT_AGENT_API_KEY=$(gcloud secrets versions access latest --secret=my-agent-api-key)

expert test --schema ./agent_schema.yaml      # all suites
expert test --suite 05_ask_latency            # single suite
expert test --list                            # discover suites
```

Suites shipped:

| Suite             | Offline? | Asserts                                                 |
|-------------------|:--------:|---------------------------------------------------------|
| `01_validate`     | yes      | `expert validate` succeeds on the agent schema          |
| `02_create`       | yes      | `expert init --yes` scaffolds + validates out of the box|
| `03_update`       | yes      | Edit → validate loop preserves schema integrity         |
| `04_deploy`       | no       | `/health`, `/ready` respond 200; unauth calls get 401   |
| `05_ask_latency`  | no       | Warmup + steady-state TTFT budgets + cache hit signal   |
| `06_sessions`     | no       | LGPD: create → list → delete round-trip                 |

### Reusable GitHub Actions workflow

Private agent repos inherit the same suites via a reusable workflow — no
submodules or copy-paste. See
[`.github/workflows/expert-e2e.yml`](.github/workflows/expert-e2e.yml):

```yaml
jobs:
  e2e:
    uses: feliperbroering/expert-agent/.github/workflows/expert-e2e.yml@main
    with:
      schema: ecg-expert/agent_schema.yaml
      suite: 05_ask_latency                  # optional — omit to run all
    secrets:
      endpoint: ${{ secrets.EXPERT_AGENT_ENDPOINT }}
      api-key:  ${{ secrets.EXPERT_AGENT_API_KEY }}
```

> **Wiring this into a private repo for the first time?** Follow
> [`docs/AGENT_E2E_SETUP.md`](docs/AGENT_E2E_SETUP.md) — a copy-pasteable,
> agent-friendly checklist that takes you from "empty repo with a schema" to
> "green nightly E2E job" in five steps.

---

## Authentication

Cloud Run uses **two layers of bearer auth**, intentionally:

| Header                          | Audience                | Required for                   |
|---------------------------------|-------------------------|--------------------------------|
| `X-Serverless-Authorization`    | Cloud Run IAM (ID token)| Reaching the service at all    |
| `Authorization: Bearer <KEY>`   | App layer (admin key)   | `/ask`, `/docs/sync`, `/memory`|

The split avoids the well-known collision where Cloud Run's IAM strips
`Authorization` before the app sees it. Public endpoints (`/health`,
`/ready`) only need the ID token.

For local dev you can run with `APP_ENV=development` and disable the
admin-key check entirely (see `backend/app/auth.py`).

---

## Repository layout

```
backend/        FastAPI app (`app.main:app`) + tests
  app/llm/      LLMClient protocol + Gemini AI Studio / Vertex implementations
  app/cache/    Context Cache manager + background refresher
  app/docs/     Manifest model + DocsSyncService (incremental SHA diff)
  app/memory/   Short-term (Firestore) + long-term (MemPalace/Chroma) + orchestrator
  app/routes/   /ask /docs/sync /sessions /memory /health
cli/            `expert` (Typer + Rich)
example-schema/ Annotated AgentSchema + prompt template
infra/          OpenTofu stacks: platform, chroma, agent (per agent)
scripts/        bootstrap-project.sh, bootstrap_docs_to_gcs.py
.github/workflows/  ci.yml, release-please.yml, deploy.yml
```

---

## Cost ballpark

For a single project hosting one or more agents on `us-central1` (or
similar), idling on Cloud Run scale-to-zero:

| Component                            | Idle           | Notes                                  |
|--------------------------------------|----------------|----------------------------------------|
| Chroma server (Cloud Run, min=max=1) | **~$40 / mo**  | Always-on, shared across all agents    |
| Each agent (Cloud Run, min=0)        | **~$0**        | Pay only on request                    |
| Firestore                            | **~$0**        | Free tier covers low-QPS use           |
| Gemini Pro requests                  | **variable**   | `cached_tokens` are heavily discounted |
| GCS storage                          | **~$0.02/GiB** | Docs + memory snapshots                |

Headline efficiency win: with Context Caching on, a typical `/ask` against
a ~800 k-token corpus shows `cached_tokens / input_tokens ≈ 0.999`, i.e.
the prompt portion of the cost is essentially flat regardless of how big
your corpus is.

---

## Roadmap

- [ ] Vertex AI client tested at parity with AI Studio (grounding + cache).
- [ ] Built-in evaluation harness (`expert eval` against gold Q&A pairs).
- [ ] OpenTelemetry export wired into Cloud Trace by default.
- [ ] Multi-tenant agent (per-tenant memory + cache) for SaaS use cases.
- [ ] Web UI / playground for non-technical curators.
- [ ] `release-please`-driven versioned container tags pushed to GHCR.

---

## Contributing

Issues and PRs are welcome. The project follows
[Conventional Commits](https://www.conventionalcommits.org/) and uses
[release-please](https://github.com/googleapis/release-please) for SemVer
automation. Run the full check suite with:

```bash
uv sync --extra dev --extra vertex --extra otel
uv run ruff check .
uv run mypy backend cli
uv run pytest
```

---

## License

Apache-2.0 — see [LICENSE](./LICENSE).
