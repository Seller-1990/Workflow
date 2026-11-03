# Path execution without redundant consent

## Applicability

Read when changing imported script/cwd handling, run entry points, RunPlan
snapshots, or legacy path-review compatibility. This contract supersedes the
scoped-consent policy on 2026-10-30 after the user explicitly chose removal from
**all run entry points**, not only desktop clicks. The filename is retained to
preserve existing references; historical evidence is not the current policy.

## Required behavior

- Desktop, CLI, engine and automatic triggers must not ask for or require a
  second acceptance of absolute paths or parent-directory references.
- Legacy `risky_paths_review_required`, revisions and confirmation digests must
  not prevent execution, including unconfirmed imports and stale/scoped digests.
- Keep database schema/legacy storage compatibility; no migration, batch rewrite
  or silent confirmation write is required to run an existing workflow.
- Keep the legacy CLI `--confirm-risky-paths` flag parse-compatible as a documented
  no-op if retained. Ordinary runs and retries must not read interactive input.
- Preserve complete immutable RunPlan execution snapshots, actual mode selection,
  valid configuration/arguments, missing-file errors, run exclusion, cancellation,
  stop confirmation and process/log ownership contracts.
- The permission change does not remove post-execution manual/background/orphan
  risk diagnostics. Those describe unfinished cleanup, not path consent.

## Forbidden behavior

- Removing only the GUI prompt while leaving a CLI or engine trust gate.
- Bypassing consent by marking all workflows trusted or widening a saved digest.
- Adding bypass flags or a parallel run implementation for each entry point.
- Deleting unrelated validation or lifecycle tests as though all warnings were
  the retired path-confirmation requirement.

## Required validation

- Unconfirmed import and stale digest reach safe fake/demo executor boundaries.
- Non-TTY CLI without the old flag can run; old flag has no authorization write.
- Retry without history reports the engine's ordinary error, not a trust error.
- UI single-step unchecked, checked, cancelled and save-defaults semantics remain.
- Missing files, malformed arguments, invalid ranges/modes and stop confirmation
  retain their existing behavior.
- Test path normalization/digest/database compatibility independently of run
  authorization; retained helpers must not reintroduce runtime consent.

## Related contracts

- [Workflow-start progress](./workflow-start-progress.md)
- [Executor output ownership](./executor-output-ownership.md)
- [Context curation](../context-curation.md)
