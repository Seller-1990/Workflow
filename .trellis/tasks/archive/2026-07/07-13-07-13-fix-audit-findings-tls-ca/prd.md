# Fix Audit Findings and Packaged TLS CA

## Goal

Fix the packaged DingTalk TLS CA bundle failure and implement the actionable audit findings, excluding encryption or relocation of stored Webhook access tokens as explicitly requested.

## Scope

- Resolve and configure a valid CA bundle for requests in source and PyInstaller builds.
- Add a packaged self-check that exercises the same CA resolution used by notifications.
- Create a verified SQLite snapshot before pending schema migrations.
- Enforce release tag and APP_VERSION consistency.
- Run tests in the macOS packaging job and expose platform capabilities in the step editor.
- Log shutdown failures instead of swallowing them.
- Fail explicitly on corrupted execution-critical JSON configuration.
- Add session cleanup guarantees at application/CLI lifecycle boundaries without breaking existing ORM-return contracts.
- Update tests, release version, README release notes, and the audit report disposition.

## Out of Scope

- Encrypting or moving Webhook access tokens out of SQLite.
- Broad rewrites of MainWindow, WorkflowEngine, or the database facade.
- Replacing PySide6, SQLAlchemy, or other justified dependencies.

## Validation

- Add a regression test reproducing a missing certifi.where() path with a valid bundled candidate.
- Run targeted tests after each vertical change.
- Run all repository quality guards, compileall, and full pytest.
- Build the release executable and run its isolated --self-check when feasible.