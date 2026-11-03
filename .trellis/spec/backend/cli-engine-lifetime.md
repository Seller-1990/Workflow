# CLI engine lifetime

## Applicability

Read when a command constructs CLIEngine or changes run/retry/dry-run shutdown.

## Required behavior

- After successful construction, close the engine exactly once through finally on
  normal return, cancellation, query/preflight/execution/output failure, or exit.
- Preserve command return/exit codes and error propagation. Do not close an
  unconstructed object or replace the primary execution error with routine output.
- Reuse the existing close/shutdown implementation and main session cleanup.
  Legacy retired path-confirmation flags remain compatible no-ops.

## Forbidden behavior

- Sequential-only close after a potentially raising operation.
- Suppressing exceptions or changing cancelled/notification state merely to
  guarantee a success exit.

## Required validation

Inject failures after construction at reached query/run/dry-run/output boundaries.
Assert close count, propagated error and existing normal/false-return exit codes.
Keep parser, range, notification, cancellation and subprocess help regressions.

## Related contracts

- [Directory structure](./directory-structure.md)
- [Path execution without redundant consent](./scoped-path-confirmation.md)
