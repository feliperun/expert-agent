# Security Policy

## Supported versions

`expert-agent` is in alpha. Security fixes are shipped against the latest `main` and the most recent tagged release. Older releases are not patched — please upgrade.

| Version  | Supported          |
|----------|--------------------|
| `main`   | ✓ (latest fixes)   |
| `0.1.x`  | ✓ (latest tag)     |
| `< 0.1`  | ✗                  |

## Reporting a vulnerability

**Please do not open a public GitHub issue.**

Report vulnerabilities privately through one of:

1. **GitHub private advisory** — [new advisory](https://github.com/feliperbroering/expert-agent/security/advisories/new) (preferred — keeps the timeline tied to the repo).
2. **Email** — [hi@felipe.run](mailto:hi@felipe.run) with subject `[expert-agent security]`. Please include:
   - A description of the issue and its impact.
   - Steps to reproduce (or a proof-of-concept).
   - The commit SHA or version you tested against.
   - Your preferred contact method for the follow-up.

You'll get an acknowledgement within **72 hours** and a triage update within **7 days**.

## Disclosure timeline

1. **Day 0** — you report privately.
2. **Day ≤ 3** — we acknowledge and start triage.
3. **Day ≤ 30** — we ship a fix on `main` and cut a patch release. For critical issues we aim for ≤ 7 days.
4. **Day ≤ 60** — we publish a GitHub Security Advisory crediting you (unless you opt out).

If a fix cannot land in 60 days (e.g. requires upstream changes in Gemini, Chroma, or FastAPI), we'll coordinate the disclosure window with you.

## Scope

In scope:

- `backend/` — FastAPI app, auth middleware, data-handling paths.
- `cli/` — command-injection, credential handling, file-write paths.
- `infra/` — IAM bindings, Cloud Run config, Secret Manager usage.
- Supply chain — pinned dependencies, Docker base image, CI workflow secrets.

Out of scope (please *don't* report these):

- Misconfiguration of **your** GCP project or leaked API keys you created.
- Volumetric DoS against a self-hosted deploy (Cloud Run throttling is your config).
- Vulnerabilities in Gemini, Firestore, Chroma, or other upstream services — report those to the upstream maintainer.
- Social engineering of maintainers.

## Hardening checklist for operators

If you self-host an expert agent, here's the short audit we suggest running:

- **Rotate admin keys** regularly (`admin-key-<agent>` secret version bump).
- Keep **`APP_ENV=production`** — development mode disables the bearer-key check.
- Scope the **Cloud Run service account** to exactly the secrets + GCS prefixes it needs.
- Use **CMEK** (customer-managed encryption keys) on GCS + Firestore if your data sensitivity requires it.
- Pin the backend image by **digest**, not by tag, in your `tofu apply`.
- Enable **Cloud Run request logging** + **VPC Service Controls** if you're in a regulated environment.

## Credits

Security contributors will be listed in release notes and (if desired) in a `SECURITY_HALL_OF_FAME.md`. Thanks for keeping this project safe.
