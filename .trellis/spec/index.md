# Spec index (router)

> **Scope**: Project Trellis specs under `.trellis/spec/`.
> **Governance**: [context-curation.md](./context-curation.md) (`spec-research-context-v1`).

This file is a **router only**. It must not duplicate leaf contract bodies.

## Applicability

1. Writing or splitting Specs / Research? → Read [context-curation.md](./context-curation.md).
2. Writing `implement.jsonl` / `check.jsonl`? → Same contract (JSONL allowlist).
3. Package- or layer-specific coding rules? → Follow package `index.md` links below (add as packages appear).

## Governance contracts

| Contract | When to read |
|----------|----------------|
| [context-curation.md](./context-curation.md) | Any Spec write/split; Research structure; task manifests |

## Package / layer routers

Add links as you create them, for example:

| Area | Index |
|------|--------|
| Thinking guides | [guides/index.md](./guides/index.md) (if present) |
| Backend | [backend/index.md](./backend/index.md) |
| Qt UI | [ui/index.md](./ui/index.md) |

## Validation entry points

- Spec leaves: one independently applicable contract each.
- Indexes: applicability + links + validation only.
- Task manifests: only Spec leaf paths and `*-summary.md` Research summaries.

## Notes

- Seeded from user global defaults: `~/.trellis/defaults/spec/`.
- After `trellis init`, run `~/.trellis/scripts/seed-context-curation.ps1` (or use `trellis-init.ps1` wrapper) if these files are missing.
- Pre-adoption task archives are frozen; do not mass-migrate for style.
