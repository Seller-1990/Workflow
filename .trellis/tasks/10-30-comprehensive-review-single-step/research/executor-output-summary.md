# Executor output ownership — continuation summary

## Conclusion and evidence status

The frozen Python/BAT correction gives each pipe one reader and separates future sink-operation authorization from safe physical log closure. Mainline rejected the original 94-pass intermediate snapshot after reproducing an unbounded sink-lock wait. The replacement uses short state transitions, no state lock across sink I/O, per-operation write/flush authorization, and deferred log closure when an operation is already in flight. The existing engine/history consumers now retain known risks without changing parent success or cancellation classification.

Mainline read the final source and return-before-release assertions, then executed the integrated full suite: **714 passed, 1 skipped, 2 existing warnings in 111.45s**, exit 0; 715 tests collected. A separate actual-capture → real engine → isolated SQLite StepLog → risk-count → history probe passed for success/cancellation. Full broad-except and risky-call audits passed; hotspot checks failed (35 baseline regressions, 5 files over 1000 lines), and strict hygiene failed on local residues. The completed finite independent read-only Phase 5 review found no actionable correctness issue at confidence >=80 in the named delta. It ran no tests and made no edits; its verdict is separate from mainline execution evidence. Scoped Phase 5 acceptance is complete under the stated physical-I/O limits, not a claim that every quality gate passed or the whole project is defect-free.

## Selected decision and implementation constraints

- Investigate Python/BAT only: stdout/stderr reading, log writes/closure, cleanup, and result visibility.
- Each pipe must have one reader. Do not use communicate to compete with a started stream reader.
- Log closure must synchronize with writes; detachment revokes new writes and surviving readers must not use closed files. If an externally stalled operation is already in flight, its owner defers safe closure until that operation returns; do not claim bounded return can forcibly stop arbitrary I/O or prevent its eventual completion.
- Process waits and reader joins use finite timeouts; detach must not wait for active sink I/O via the state lock. Physical close and filesystem I/O retain the explicit boundary below. Never close a potentially blocked buffered pipe from the main thread in a way that adds an unbounded lock wait.
- Preserve cancellation classification and non-retryable markers; make incomplete capture / residual activity visible via existing result policy rather than claiming all descendants stopped. The successful executor → StepResult projection now conditionally retains known-policy diagnostics; ordinary success still ignores arbitrary informational text and note-only/false/unknown flags. This is a minimal existing-consumer correction, not a general engine rewrite.
- Persist known-risk diagnostics on successful parent exit without changing its success status. The history diagnostic formatter must also retain known risk notes for success/cancelled records; no-risk wording remains unchanged. This is a minimal existing-consumer adaptation, not a new UI feature or result schema.
- Do not blindly kill descendants on normal parent exit: intentional background applications may exist.
- Cover normal exit, cancel, timeout, partial thread-start failure, read/write failures, and late output. Put reachability/effect assertions outside swallowed executor exceptions.
- Prefer one small shared ownership helper over duplicated synchronization in both executors; no generic process framework or new dependency.
- Existing subprocess environment, decoding order, log path, CLI/UI and engine interfaces must remain compatible unless a concrete bug requires a narrowly documented change.

## Boundaries retained

Previous 611 passed / 1 skipped / 2 warnings belongs only to the pre-continuation snapshot; the current frozen source has the separately executed 714-pass result above. Already authorized I/O may finish after return; future operations are revoked and active log ownership closes safely when that I/O returns. Idle-file physical close is synchronous, and neither it nor pre-capture setup or other filesystem I/O has a universal deadline. A failure after the result snapshot cannot retroactively change that result; pending capture/ownership is reported. A surviving reader may remain until a descendant releases the pipe. No commit, push, packaging, version bump, new dependency, data deletion, cross-process cancellation, DB migration, or unknown-commit reconciliation. Process-tree termination is best-effort; this follow-up does not promise arbitrary descendant termination.

## Evidence routing

Read `research/evidence/executor-output-ownership.md` for deterministic reproduction, rejected alternatives, actual tests and implementation decisions, and `research/evidence/executor-output-final-review.md` for the separately returned independent verdict and challenged interleavings. Use this summary, not evidence or planning files, in manifests.
