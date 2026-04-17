# Private agent repo guide

This guide shows the cleanest way to create a **private repo for your own specialist agents** while reusing the open-source `expert-agent` framework.

Use it when you want:

- private prompts and docs
- your own deploy cadence
- one repo with one agent, or one repo with many agents
- the same `expert` CLI and Robot Framework E2E kit from the public repo

---

## Recommended repo shapes

### Option A — one repo, one agent

Best when each agent has its own owner, deploy cadence, and secrets.

```text
my-private-agent/
├─ agent_schema.yaml
├─ prompts/
│  └─ identity.md
├─ docs/
│  ├─ paper-1.pdf
│  └─ protocol.md
├─ expert.toml                 # optional in single-agent repos
└─ .github/workflows/
   └─ e2e.yml
```

This gives you the nicest UX:

```bash
expert validate
expert count-tokens
expert sync
expert ask "..."
```

### Option B — one repo, many agents

Best when the agents share docs, ownership, or infra.

```text
my-private-agents/
├─ expert.toml
├─ cardiology/
│  ├─ agent_schema.yaml
│  ├─ prompts/
│  └─ docs/
├─ dermatology/
│  ├─ agent_schema.yaml
│  ├─ prompts/
│  └─ docs/
└─ oncology/
   ├─ agent_schema.yaml
   ├─ prompts/
   └─ docs/
```

Then use the workspace-aware CLI:

```bash
expert agents
expert @cardiology validate
expert @dermatology ask "..."
expert use oncology
expert which
```

---

## Step 1 — install the CLI

On your machine:

```bash
uv tool install "git+https://github.com/feliperbroering/expert-agent.git"
expert --version
```

If you also want the packaged Robot Framework kit:

```bash
uv tool install "expert-agent[test] @ git+https://github.com/feliperbroering/expert-agent.git"
```

---

## Step 2 — scaffold the repo

### Single-agent

```bash
mkdir my-private-agent && cd my-private-agent
expert init .
```

### Multi-agent

```bash
mkdir my-private-agents && cd my-private-agents
expert init cardiology
expert init dermatology
expert init oncology
```

Then add `expert.toml`:

```toml
default_agent = "cardiology"

[agents.cardiology]
schema = "cardiology/agent_schema.yaml"
endpoint_env = "CARDIOLOGY_AGENT_ENDPOINT"
api_key_env = "CARDIOLOGY_AGENT_API_KEY"

[agents.dermatology]
schema = "dermatology/agent_schema.yaml"
endpoint_env = "DERM_AGENT_ENDPOINT"
api_key_env = "DERM_AGENT_API_KEY"

[agents.oncology]
schema = "oncology/agent_schema.yaml"
endpoint_env = "ONCO_AGENT_ENDPOINT"
api_key_env = "ONCO_AGENT_API_KEY"
```

`expert.toml` is optional but recommended in private multi-agent repos because it:

- makes endpoints and secret env vars explicit
- avoids ambiguity when names overlap
- gives you a default agent

---

## Step 3 — add your private knowledge base

For each agent:

1. Edit `prompts/identity.md`
2. Replace the placeholder file in `docs/`
3. Keep sensitive source material **out of git** unless your repo policy allows it

Recommended patterns:

- Commit curated Markdown summaries and public PDFs
- Keep raw source dumps, exports, and OCR artifacts in a private storage bucket
- Add `_drafts/` to the schema's `exclude_patterns`

Validate locally:

```bash
expert validate
expert count-tokens
```

Or, in a multi-agent repo:

```bash
expert @cardiology validate
expert @cardiology count-tokens
```

---

## Step 4 — deploy

The easiest mental model is:

- `infra/platform` = once per GCP project
- `infra/chroma` = once per GCP project
- `infra/agent` = once per agent

If your private repo only contains the agent specs, you still have two clean options:

### Option A — central infra repo

Keep OpenTofu in a separate infra repo and point it at the backend image + agent IDs. This is the cleanest setup for teams.

### Option B — vendor/copy the `infra/` folder

Copy `infra/` into your private repo and own it there. This is simpler if you're a solo maintainer and want one repo to rule everything.

If you're bootstrapping from scratch, start with the public repo's `infra/` folder and [`infra/README.md`](../infra/README.md).

---

## Step 5 — wire local defaults

After deploy, export endpoint + API key:

```bash
export EXPERT_AGENT_ENDPOINT="https://my-agent-xxxx.a.run.app"
export EXPERT_AGENT_API_KEY="$(gcloud secrets versions access latest --secret=admin-key-my-agent)"
```

Now the bare commands work:

```bash
expert sync
expert ask "..."
```

For multi-agent repos, prefer per-agent env vars referenced by `expert.toml`:

```bash
export CARDIOLOGY_AGENT_ENDPOINT="https://cardiology-xxxx.a.run.app"
export CARDIOLOGY_AGENT_API_KEY="..."

export DERM_AGENT_ENDPOINT="https://derm-xxxx.a.run.app"
export DERM_AGENT_API_KEY="..."
```

Then:

```bash
expert @cardiology ask "..."
expert @dermatology sync
```

---

## Step 6 — CI with the reusable E2E workflow

Create `.github/workflows/e2e.yml` in your private repo.

### Single-agent repo

```yaml
name: expert-e2e

on:
  pull_request:
  workflow_dispatch:

jobs:
  e2e:
    uses: feliperbroering/expert-agent/.github/workflows/expert-e2e.yml@main
    with:
      schema: agent_schema.yaml
    secrets:
      endpoint: ${{ secrets.EXPERT_AGENT_ENDPOINT }}
      api-key: ${{ secrets.EXPERT_AGENT_API_KEY }}
```

### Multi-agent repo

```yaml
name: expert-e2e

on:
  pull_request:
  workflow_dispatch:

jobs:
  e2e:
    strategy:
      fail-fast: false
      matrix:
        agent:
          - name: cardiology
            schema: cardiology/agent_schema.yaml
            endpoint_secret: CARDIOLOGY_AGENT_ENDPOINT
            api_key_secret: CARDIOLOGY_AGENT_API_KEY
          - name: dermatology
            schema: dermatology/agent_schema.yaml
            endpoint_secret: DERM_AGENT_ENDPOINT
            api_key_secret: DERM_AGENT_API_KEY
    uses: feliperbroering/expert-agent/.github/workflows/expert-e2e.yml@main
    with:
      agent: ${{ matrix.agent.name }}
      schema: ${{ matrix.agent.schema }}
    secrets:
      endpoint: ${{ secrets[matrix.agent.endpoint_secret] }}
      api-key: ${{ secrets[matrix.agent.api_key_secret] }}
```

More detail: [`docs/AGENT_E2E_SETUP.md`](./AGENT_E2E_SETUP.md).

---

## Suggested repo extras

If you're making the private repo pleasant for future-you or for teammates, add:

- `README.md` with the repo's purpose + the list of hosted agents
- `expert.toml` even in single-agent repos if you want explicit endpoint wiring
- `.gitignore` covering PDFs, exports, `.env`, and generated reports
- `docs/OPERATIONS.md` with deploy / rotate-key / rollback steps
- `.github/CODEOWNERS` if multiple specialists own different agents

Nice next step:

- add a tiny `Makefile` or `justfile` with `validate`, `sync`, `ask`, `e2e`

---

## Suggested `.gitignore`

```gitignore
.env
.venv/
.expert/
report.html
log.html
output.xml
*.tfstate
*.tfstate.*
*.tfplan
docs/_raw/
docs/_exports/
```

---

## Common workflows

### Single-agent daily loop

```bash
expert validate
expert count-tokens
expert sync
expert ask "what changed in the 2025 guideline?"
```

### Multi-agent daily loop

```bash
expert agents
expert @cardiology validate
expert @cardiology sync
expert @cardiology ask "..."
expert @dermatology ask "..."
```

### Pin one agent for the day

```bash
expert use cardiology
expert ask "..."            # targets cardiology
expert which
expert use --clear
```

---

## Decision guide

Choose **one repo per agent** when:

- each agent has its own deploy cadence
- prompts/docs are highly sensitive
- different teams own different agents

Choose **one repo with many agents** when:

- the same team curates all agents
- the agents share domain docs or infra
- you want one CI surface and one CLI workspace

If you're unsure, start with **one repo per agent**. You can always merge into a multi-agent workspace later with `expert.toml`.
