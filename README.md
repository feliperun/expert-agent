# expert-agent

> Ultra-specialist AI agents as a service — **NotebookLM as an API**, powered by
> Gemini 3.1 Pro long-context + context caching, with multi-layer persistent
> memory.

[![CI](https://github.com/feliperbroering/expert-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/feliperbroering/expert-agent/actions/workflows/ci.yml)

**Status:** 🚧 alpha — under active development.

## What is this?

`expert-agent` is a reusable microservice template for building AI agents that
are **ultra-specialized in a single knowledge domain**. You give it:

1. A **system prompt** defining the agent's identity.
2. A **directory of reference documents** (PDFs, markdown, text).
3. A **YAML schema** describing the agent's behavior.

...and you get a **Cloud Run service** that exposes an HTTP API with:

- Long-context grounding (up to ~700k tokens of reference material, cached).
- Persistent conversational memory (short-term session + long-term verbatim recall).
- Streaming responses with citations.
- LGPD-friendly session management.

## Architecture at a glance

```
┌──────────────┐        ┌──────────────────┐        ┌──────────────┐
│   CLI/HTTP   │───────▶│ agent (Cloud Run)│───────▶│  Gemini API  │
└──────────────┘        │ FastAPI, Python  │        └──────────────┘
                        └────┬─────────┬───┘
                             │         │
                    ┌────────▼──┐   ┌──▼─────────────┐
                    │ Firestore │   │ Chroma HTTP    │
                    │ (session) │   │ (Cloud Run)    │
                    └───────────┘   └────────────────┘
                                             │
                                    GCS FUSE │ persist
                                             ▼
                                    gs://{proj}-memory
```

See [`agent-expert.plan.md`](./agent-expert.plan.md) (gitignored) for the full
design document.

## Quick start

Coming soon. Check back for the full deploy guide.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
