# StepLog creation identity

## Applicability

Read when creating StepLogs, retrying database writes, or upgrading persistence for
creation recovery. This contract concerns recording an execution, not executing a
business script exactly once.

## Required behavior

- Assign an immutable operation identity before the first INSERT. Reuse it after
  failed/unknown commit outcomes. Explicit callers may reuse it across calls and
  processes; legacy calls without a key allocate one fresh identity per call.
- A persisted uniqueness constraint arbitrates simultaneous calls. Reusing a key
  with the same creation payload returns the same row, including its current
  status; incompatible run/step/order/initial-note payloads fail explicitly.
- An unknown commit outcome is reconciled through a clean transaction before a
  retry. A failed reconciliation must not authorize a new unkeyed INSERT.
- Engine scheduling reuses one identity for one logical run/step log; executor
  business retries continue updating that row. Different operations remain legal.
- Migration is additive and restartable. Retain all legacy rows, including
  duplicate run/step pairs, without choosing a winner or rewriting history.

## Forbidden behavior

- Blind INSERT after commit uncertainty, or a run/step UNIQUE constraint applied
  to old duplicate data by deleting/deduplicating rows.
- Treating post-commit refresh failure as evidence that commit failed.
- Claiming StepLog idempotency makes external scripts exactly-once.
- Opening or migrating the real working database in this task's validation.

## Required validation

Use isolated SQLite databases for commit-before-write failure, commit-then-raise,
refresh failure, replay, competing sessions/processes, incompatible payload and
unavailable reconciliation. Assert reached fault boundaries and actual row IDs
and counts. Upgrade a populated v11-shaped database with duplicate old StepLogs,
rerun/interruption-recover the migration, and prove retained rows.

## Related contracts

- [Run ownership and cancellation](./run-ownership-cancellation.md)
- [Directory structure](./directory-structure.md)
