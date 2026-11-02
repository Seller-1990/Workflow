# Persisted run ownership and cancellation

## Applicability

Read when claiming a RunHistory, stopping a history ID, polling cancellation, or
finalizing/releasing an owned run. This contract is for local processes sharing
one SQLite database, not remote arbitrary process termination.

## Required behavior

- Persist ownership bound to the exact history/run identity as part of publishing
  the new history. Include an unguessable owner identity and verifiable local
  process identity. Preserve same-engine create/register locking and nested runs.
- Nonowners request cancellation durably for that exact owner/run. They do not
  change a live run or its steps to a terminal state. Repeated requests are safe.
- The owner observes requests through a bounded polling/collaborative cancellation
  path, acknowledges them, and alone performs live execution finalization. Pollers
  and sessions are closed on every success/failure/cancel/startup-exception path.
- Distinguish request accepted, acknowledged, completed, and owner unreachable in
  returned/logged state. Acceptance is not proof that the script has stopped.
- Do not equate a missing local active ID, expired heartbeat, or failed liveness
  check with proven owner death. Unknown/foreign-host/permission-denied liveness
  remains unreachable; only released/proven-dead owners permit orphan cleanup.
- Protect normal terminal results against concurrent stop requests and stale
  requests. A request for an old owner cannot cancel a new run or another target.
- Keep legacy ownerless history cleanup compatible. Nested target cancellation
  retains existing shared-engine propagation rather than silently changing scope.
- An outer run must not start while earlier active runs or reserved child slots
  remain. A nested request whose own cancellation event is already set must return
  before shared startup writes, history publication or observer startup; a worker
  can be RUNNING before reserving its child slot. Preserve existing lock order.
- Keep uncertain publication candidates separate from verified execution identities.
  Clean recovery must match history, run and owner token before adoption. An
  unverified candidate may only be released with the full identity predicate;
  never pass it to an ordinary numeric-ID-only finalizer.

## Forbidden behavior

- A second process immediately writes cancelled while the first still executes.
- Guessing a live target from an empty activity set or PID alone after reuse.
- Writing terminal RunHistory after unfinished-step cleanup failed.
- Claiming the protocol terminates arbitrary descendants or blocked physical I/O.
- Opening/migrating the real working database for this task's validation.

## Required validation

Use real separate processes and isolated SQLite: owner blocked in a controlled
safe executor, second process requests stop, nonterminal-before-owner-response,
owner acknowledgement/actual cancellation, already-terminal race, startup request,
wrong/stale identity, repeated request, dead/released/unknown owner, initialization
failure, and nested ownership cleanup. Use explicit reached assertions outside
engine catch boundaries. Verify no leaked polling threads and migration restart.
Gate real child workers before slot reservation, before publication and after
context restoration; let parent timeout/grace actually cancel them. Check that
stale workers cannot publish or change healthy/already-cancelled next-root state,
and that normal nested/post-cleanup runs still work. Inject acknowledgement loss,
first clean-reader failure and replacement rows with reused numeric/run IDs but a
different owner; only the exact published claim may be adopted or released.

## Related contracts

- [Startup-stop ownership](./startup-stop-ownership.md)
- [StepLog creation identity](./step-log-idempotency.md)
- [Executor output ownership](./executor-output-ownership.md)
