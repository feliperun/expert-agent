# RFC: Google Drive connector for knowledge sync

**Status:** draft  
**Authors:** expert-agent maintainers  
**Consumers:** private agent repos that mirror Drive folders into `docs/`

## Problem

Many teams keep canonical SOPs and manuals in Google Drive (Docs, PDFs, DOCX).
The expert-agent pipeline today expects files under `<agent>/docs/` and syncs them
to GCS + Gemini Context Cache via `expert sync` / `POST /docs/sync`.

Private repos currently bridge this gap with ad-hoc scripts (e.g.
`import-*-drive.py`). We need a **generic, framework-level** connector that:

1. Lists files in an authorized Drive folder (recursive).
2. Exports supported MIME types to `.md` / `.pdf` / `.txt`.
3. Writes frontmatter metadata (`source_url`, `drive_file_id`, `slug`).
4. Triggers the existing manifest sync (no duplicate cache logic).

## Goals

- Parametrize folder ID, credentials, and export map via `agent_schema.yaml`.
- Reuse `DocsSyncService` — Drive is an **ingest** step, not a new cache path.
- Support dry-run and incremental diff (skip unchanged `modifiedTime` + `md5`).
- Work with user ADC and service accounts (`drive.readonly` scope).

## Non-goals

- Real-time Drive webhooks (phase 2).
- Indexing Shared Drives without explicit folder ID (phase 2).
- Storing Drive credentials in the agent container image.

## Proposed schema extension

```yaml
spec:
  knowledge:
    reference_docs_dir: ./docs
    include_patterns: ["*.md", "*.pdf"]
    drive_sync:                    # optional
      enabled: true
      folder_id: "${DRIVE_FOLDER_ID}"
      credentials_env: DRIVE_CREDENTIALS_JSON  # optional SA path
      export:
        google_docs: markdown
        docx: pdf
      frontmatter:
        - source_url
        - drive_file_id
        - slug
```

## CLI surface

```bash
expert drive pull --agent my-expert          # dry-run report
expert drive pull --agent my-expert --apply  # write docs/ + optional auto-sync
expert drive pull --search "quality"         # discover candidate folders
```

## Backend changes

None required for v1 if ingest remains CLI-side. Optional future endpoint:

`POST /docs/ingest/drive` (admin-only) for Cloud Run environments without local
`docs/` — out of scope for v1.

## Security

- Scope: `https://www.googleapis.com/auth/drive.readonly` minimum.
- Folder ID is an allowlist boundary — document in agent README.
- Never log file contents; log file IDs and slugs only.

## Testing

- Unit: MIME export map, slugify, frontmatter rendering.
- Integration: mock Drive API (`googleapiclient` test double).
- E2E: synthetic Drive folder in a test GCP project.

## Rollout

1. Merge RFC + schema fields (no default — opt-in).
2. Implement `cli/expert/commands/drive.py`.
3. Document in `example-schema/agent_schema.yaml`.
4. Private repos delete interim `import-*-drive.py` scripts after adoption.

## Open questions

- Should `source_url` be mandatory in identity prompts (private concern) or
  schema-level `citation.required_fields`?
- Minimum token count for Context Cache (Gemini ≥ 2048) — validate at
  `expert validate` time when `context_cache.enabled: true`?
