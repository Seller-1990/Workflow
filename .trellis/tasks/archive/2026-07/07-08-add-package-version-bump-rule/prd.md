# PRD: Add Packaging Version Bump Rule

## Goal

Add a project rule requiring version increments before packaging after completed
changes.

## Requirements

- For small scoped fixes or optimizations, increment the patch version before
  packaging, e.g. `4.1.2 -> 4.1.3`.
- For broad changes, major refactors, or major features, increment the major
  version and reset minor/patch, e.g. `4.1.3 -> 5.0.0`.
- Do not use the minor version automatically unless the user explicitly requests
  a minor release.
- Keep this as a durable project rule for future agents.
- Do not change the current app version during this rules-only update.

## Acceptance Criteria

- The project rules file records the packaging version bump policy.
- The wording is concrete enough to execute before future packaging.
- Existing unrelated working-tree changes remain untouched.
