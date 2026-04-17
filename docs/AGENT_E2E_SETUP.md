# Wiring `expert test` into a private agent repo

> **Audience.** Another LLM coding agent (or a human) tasked with adding the
> packaged Robot Framework end-to-end kit to a *private* repository that hosts
> one or more `expert-agent` deployments.
>
> **Promise.** Following this document end-to-end gets you: a green CI job that
> runs the same suites the upstream uses on every push, a manual "run this
> suite now" trigger, and a nightly regression catcher — all without vendoring
> a single line of test code.

---

## 0. Mental model (read once, then skip)

The test kit lives **inside** the `expert-agent` wheel. Anyone who installs
`expert-agent[test]` automatically gets:

- the CLI command `expert test` (a Robot Framework runner),
- six `.robot` suites under `cli/expert/testkit/suites/`,
- a custom `ExpertLibrary.py` that knows how to drive both the CLI and the
  HTTP backend.

So a private repo never copies tests. It only:

1. Says **what schema** to validate (path inside the repo).
2. Provides **two secrets** (live endpoint + API key) for the online suites.
3. References the upstream **reusable workflow** to actually run them.

That is the whole integration. If you find yourself copying `.robot` files,
**stop** — you are doing it wrong.

---

## 1. Prerequisites the private repo must satisfy

Verify these *before* writing the workflow file. If any are missing, fix them
first or warn the user.

- [ ] At least one `agent_schema.yaml` checked in (path is configurable).
- [ ] A deployed Cloud Run revision reachable at some `https://` URL.
- [ ] An admin API key for that deployment (the value of `ADMIN_KEY` env var
      in Cloud Run, usually backed by Secret Manager).
- [ ] GitHub Actions enabled on the repo (default for new repos).
- [ ] Repo settings → *Actions → General → Workflow permissions* allow
      reading from public actions (default).

If the repo hosts **multiple agents** (a monorepo), you have two options:

1. **One workflow per agent** — each file pins a different `schema:` and a
   different set of secrets. Recommended when the agents are owned by
   different teams or deployed to different projects.
2. **One workflow, matrix-over-agents** — declare an `expert.toml` at the
   repo root and let `expert test` resolve each agent by name. See the
   "matrix" snippet in [§6. Customising for your agent](#6-customising-for-your-agent).

Both integrations share the same reusable workflow; only the caller changes.

---

## 2. Add the two repository secrets

Run these once per repo, replacing the values:

```bash
gh secret set EXPERT_AGENT_ENDPOINT \
  --repo <OWNER>/<REPO> \
  --body "https://my-agent-xxxx.a.run.app"

gh secret set EXPERT_AGENT_API_KEY \
  --repo <OWNER>/<REPO> \
  --body "$(gcloud secrets versions access latest --secret=my-agent-api-key)"
```

Verify:

```bash
gh secret list --repo <OWNER>/<REPO> | grep EXPERT_AGENT_
```

The reusable workflow accepts these as `secrets.endpoint` / `secrets.api-key`
(see step 3) — the **secret names in the repo** can be whatever you want, but
keep `EXPERT_AGENT_*` for consistency with local dev (`expert ask`,
`expert test`, etc., read the same env vars).

---

## 3. Drop in the workflow file

Create one file per agent under `.github/workflows/`. Template, with the
**only** parts you must customise marked as `<<…>>`:

```yaml
name: e2e (<<agent-id>>)

# Runs the full expert-agent E2E kit against the deployed <<agent-id>> agent.
# Triggered manually or nightly. Consumes the reusable workflow shipped by
# expert-agent so that upgrades are a single `@version` bump.

on:
  workflow_dispatch:
    inputs:
      suite:
        description: "Robot suite to run (empty = all)"
        required: false
        type: choice
        default: ""
        options:
          - ""
          - "01_validate"
          - "02_create"
          - "03_update"
          - "04_deploy"
          - "05_ask_latency"
          - "06_sessions"
  schedule:
    # Nightly at 04:00 UTC — catches model / cache regressions before users do.
    - cron: "0 4 * * *"

jobs:
  e2e:
    uses: feliperbroering/expert-agent/.github/workflows/expert-e2e.yml@<<ref>>
    with:
      schema: <<path/to/agent_schema.yaml>>
      suite: ${{ inputs.suite || '' }}
      sample-question: "<<a question your agent should answer well>>"
      max-ttft-ms: "45000"     # warmup TTFT budget; relax if your model is slow
      max-total-ms: "120000"   # full-answer budget
      cli-ref: <<ref>>         # match the version of `uses:` above
    secrets:
      endpoint: ${{ secrets.EXPERT_AGENT_ENDPOINT }}
      api-key:  ${{ secrets.EXPERT_AGENT_API_KEY }}
```

### Substitution table

| Placeholder                            | Concrete example                                                              | Notes                                                                                                              |
|----------------------------------------|-------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| `<<agent-id>>`                         | `ecg-expert`                                                                  | Just for the workflow filename + display name.                                                                     |
| `<<path/to/agent_schema.yaml>>`        | `ecg-expert/agent_schema.yaml`                                                | **Must be relative to the repo root.** Validated by the reusable workflow before running.                          |
| `<<a question your agent should answer well>>` | `"Qual fórmula de correção do QTc a AHA recomenda como padrão?"` | Used by `05_ask_latency`. Pick something representative of real traffic.                                           |
| `<<ref>>`                              | `main`, `v0.1.1`, `v0.2.0`                                                    | Pin to a tag for stable runs (e.g. `v0.1.1`); use `main` only if you want to live on the bleeding edge.            |

### File naming convention

Use `e2e-<agent-id>.yml`. Examples:

```
.github/workflows/e2e-ecg-expert.yml
.github/workflows/e2e-derm-expert.yml
.github/workflows/e2e-pharma-expert.yml
```

Commit the file. **Do not** add `.gitignore` entries for `e2e-results/` — the
reusable workflow uploads them as an artifact, nothing lands on disk.

---

## 4. (Optional but recommended) Local dry run

Before pushing, validate offline that the schema parses and the harness sees
your repo correctly. You only need the offline suites for this check:

```bash
# 1. Install once.
uv tool install 'expert-agent[test] @ git+https://github.com/feliperbroering/expert-agent.git@<<ref>>'

# 2. From the repo root, point at your schema and skip the Gemini-bound suite.
expert test \
  --schema <<path/to/agent_schema.yaml>> \
  --suite 01_validate --suite 02_create --suite 03_update \
  --exclude requires-gemini \
  --output-dir /tmp/expert-e2e
```

Expected last lines:

```
expert-agent-e2e                                                      | PASS |
N tests, N passed, 0 failed
OK All suites passed.
```

If `01_validate` fails: your `agent_schema.yaml` is the problem, fix it
before opening the workflow PR.

---

## 5. Trigger the workflow and verify

```bash
gh workflow run "e2e (<<agent-id>>)" --repo <OWNER>/<REPO>
gh run watch --repo <OWNER>/<REPO>
```

A successful first run gives you:

- ✅ All 6 suites green (or only 1–3 if `EXPERT_AGENT_ENDPOINT` is unset —
  that's fine for offline-only repos).
- A `expert-e2e-reports` artifact attached to the run with `report.html` and
  `log.html`. Download with `gh run download <run-id>` and open
  `report.html` for the per-keyword timing breakdown.

If something fails, jump to **§7 Troubleshooting**.

---

## 6. Customising for your agent

You almost never need to fork the suites. Knobs available out of the box:

| Need                                   | How                                                                                                  |
|----------------------------------------|------------------------------------------------------------------------------------------------------|
| Stricter latency budget                | Lower `max-ttft-ms` / `max-total-ms` in the workflow.                                                |
| Different sample question              | Change `sample-question:` (only `05_ask_latency` consumes it).                                       |
| Skip Gemini-bound checks in CI         | Add `--exclude requires-gemini` to the runner — already the default for the reusable workflow.       |
| Run only one suite                     | Trigger with the `suite:` choice input (`gh workflow run … -f suite=05_ask_latency`).                |
| Pin to a stable upstream version       | Replace `@main` with `@v0.1.1` everywhere (both `uses:` and `cli-ref:`).                             |
| Add a per-deploy smoke check           | Call the reusable workflow from your `deploy.yml` after the Cloud Run rollout finishes.              |
| Test N agents in one monorepo          | See "matrix" snippet below, or keep one workflow-per-agent for clearer blame.                        |

### Matrix over agents (monorepo)

If `expert.toml` at the repo root declares several agents, the CLI already
understands `expert test --agent <name>`. You can call the reusable workflow
once per agent via a matrix:

```yaml
jobs:
  e2e:
    strategy:
      fail-fast: false
      matrix:
        agent:
          - { name: ecg,  schema: ecg-expert/agent_schema.yaml,  endpoint_secret: ECG_ENDPOINT,  key_secret: ECG_API_KEY }
          - { name: derm, schema: derm-expert/agent_schema.yaml, endpoint_secret: DERM_ENDPOINT, key_secret: DERM_API_KEY }
    uses: feliperbroering/expert-agent/.github/workflows/expert-e2e.yml@<<ref>>
    with:
      schema: ${{ matrix.agent.schema }}
      sample-question: "ping"
      cli-ref: <<ref>>
    secrets:
      endpoint: ${{ secrets[matrix.agent.endpoint_secret] }}
      api-key:  ${{ secrets[matrix.agent.key_secret] }}
```

Locally, the same layout lets you do:

```bash
expert agents                   # list all known agents
expert use ecg                  # pin ecg for this shell
expert ask "..."                # routes to ecg
expert @derm ask "..."          # one-off hop to derm
expert test --agent derm        # run the packaged E2E kit against derm
```

If you genuinely need a *new* assertion the upstream suites don't cover,
contribute it back to `expert-agent` rather than vendoring locally — the kit
exists exactly so every agent stays on the same baseline.

---

## 7. Troubleshooting

| Symptom (CI log)                                                                         | Root cause                                                                                                  | Fix                                                                                                                          |
|------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `error: schema not found at …`                                                          | `with.schema:` path is wrong (workflow runs from the caller checkout root).                                  | Make the path relative to repo root; verify with `ls` locally.                                                               |
| `04_deploy` fails: `Skip If    not ${has_endpoint}    EXPERT_AGENT_ENDPOINT not set`     | Secret missing or misnamed.                                                                                  | Re-run §2; confirm with `gh secret list`.                                                                                    |
| `05_ask_latency` fails with `401 Unauthorized`                                           | Wrong / stale API key.                                                                                       | Re-run §2 step 2; rotate `gcloud secrets versions add my-agent-api-key …` if needed.                                          |
| `05_ask_latency` fails on `ttft_ms` budget                                               | The deployment is genuinely slow (cold start, big context cache rebuild).                                    | Either bump `max-ttft-ms`, or set Cloud Run `min_instances >= 1` to keep one warm.                                            |
| `06_sessions` returns `404`                                                              | Backend running an old image without `/sessions` endpoint.                                                   | Redeploy with `expert-agent >= v0.1.0` and re-run.                                                                            |
| `count-tokens` test fails: `404 NOT_FOUND for model …`                                   | The Gemini model in the schema is deprecated or unavailable for `countTokens`.                               | The default workflow already excludes `requires-gemini` — if you re-included it, drop the include or fix the model in schema. |
| Workflow can't find `expert-agent/.github/workflows/expert-e2e.yml`                      | `cli-ref:` / `uses:` ref is wrong, or the upstream is private to your account.                               | Use a published tag (`v0.1.1`+) or `main`; verify with `gh api /repos/feliperbroering/expert-agent/contents/.github/workflows`. |

---

## 8. Acceptance checklist (give this back to the user when done)

- [ ] `EXPERT_AGENT_ENDPOINT` and `EXPERT_AGENT_API_KEY` secrets exist in the repo.
- [ ] `.github/workflows/e2e-<agent-id>.yml` is committed on the default branch.
- [ ] `gh workflow run "e2e (<agent-id>)"` triggers a run that completes green.
- [ ] The nightly cron is enabled (it auto-enables once the file is on the default branch).
- [ ] The workflow pins a specific `cli-ref` (don't ship `@main` to production agents — pin to a tag).
