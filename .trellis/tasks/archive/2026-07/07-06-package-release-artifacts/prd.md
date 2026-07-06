# PRD: Package Release Artifacts

## Goal

Produce a releasable Windows package for the current main branch, commit/push any required packaging fixes, and define the actionable boundary for macOS Intel packaging.

## Requirements

- Windows `build_slim2.spec` package must build successfully.
- Generated Windows executable must pass `--self-check` from an isolated app data directory.
- Any packaging-code fix must be validated with focused tests and committed/pushed.
- macOS Intel package should be produced only if the current environment can do it correctly; otherwise document the blocker and next build path clearly.

## Current Evidence

- `git push origin main` already moved `main` to `4ff0109`.
- Windows build completed but self-check failed with `ModuleNotFoundError: No module named 'backports'` from PyInstaller/pkg_resources runtime import chain.
- Current host is Windows, so native macOS `.app`/`.dmg` signing/packaging is not expected to be reliable locally.

## Validation

- Rebuild Windows package with PyInstaller.
- Run executable `--self-check` using a temp `WORKFLOW_APP_DATA_DIR`.
- Generate SHA256 checksum for the Windows artifact.
- Run focused build/CI guard tests and project package quality gates.
- Verify git status before commit and push.
