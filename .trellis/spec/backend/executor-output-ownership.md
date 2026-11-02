# Executor output ownership

## 1. Scope / Trigger

Read when changing Python/BAT stdout/stderr readers, log-file writes or closure,
process cleanup, or propagation of incomplete-output diagnostics. This is one
contract: an invocation's output capture has explicit readers and sink owners,
including after the direct process exits.

This leaf records the output-ownership contract, not a universal I/O deadline.
Consult the active research summary for source-verification evidence, the bounded
review result, and the physical-I/O limitations below.

## 2. Signatures and result boundary

- `PythonExecutor.execute(..., timeout=None, cancel_event=None, **kwargs)` and
  `BatExecutor.execute(..., timeout=None, cancel_event=None, **kwargs)` return
  `ExecutorResult` with `success`, `exit_code`, log paths, `error_message`, and
  `extra`.
- Existing result-policy fields include `cancelled`, `non_retryable`,
  `manual_required`, `background_risk`, and `note`. Use the existing policy helpers;
  do not introduce a database schema solely to carry output warnings.
- A successful process can retain `success=True` and `exit_code=0` while capture
  is incomplete. This is parent-process success, not proof that all descendants
  or readers stopped.
- The engine must retain known-policy diagnostics in `StepResult.error_message`
  and persisted `StepLog.error_message`, including on successful parent exit.
- `build_run_diagnostic(status, counts)` must retain known risk notes for
  `success` and `cancelled` as well as `failure`. No-risk text stays compatible.

## 3. Required and forbidden behavior

### Readers and pipes

- Exactly one reader consumes each stdout/stderr pipe. Do not run `communicate()`
  alongside dedicated readers, including its internally created reader threads.
- A started reader owns its pipe until it exits and releases the handle.
  If a reader never starts, the invocation retains ownership and releases that
  unused pipe without joining an unstarted thread.
- Do not close a reader-owned, potentially blocked buffered pipe from another
  thread: acquiring the pipe's internal lock can defeat a bounded cleanup.
- Ordinary EOF and read failures must both release reader-owned handles.
- A parent exit is not proof of pipe EOF. A descendant can retain a write end.

### Log and console sinks

- Revoke permission for new log/console writes before a completed capture is
  released. A late line must not initiate a write to a closed log or a subsequent
  run's console sink.
- File close must not overlap an in-flight write/flush. Track ownership rather
  than suppressing the resulting ValueError.
- For ordinary responsive file writes, logs are closed when capture finishes.
  If an already in-flight write/flush is externally stalled, bounded return and
  immediate physical closure cannot both be guaranteed. Revoke future writes,
  defer safe closure to that operation's owner, and report incomplete cleanup.
  Do not claim an in-flight operation cannot complete after executor return.
- Authorize each write and flush separately under a short state lock. A write
  authorized before detachment may still complete later; it must not authorize
  its flush, console output, or another line after detachment. Only one reader
  uses each stream's log, so a per-stream active-operation flag can own its close.
- Idle logs close synchronously. Their physical close, pre-capture log open/header
  writes/setup closure, and other filesystem I/O are not given a universal deadline
  by reader-join timeouts. State this boundary rather than claiming all cleanup is
  bounded. A deferred operation's failure after the returned result snapshot cannot
  be appended retroactively; the existing incomplete-capture warning reports its
  pending ownership.
- Sink failures are diagnostic evidence. Capture them without uncaught reader
  exceptions or masking the original process/thread-start failure.

### Waiting, outcomes, and risk

- Process cleanup waits and reader joins have finite timeouts. Do not hold the
  ownership/state lock across external sink write/flush and then wait without a
  timeout for that lock during detach: timed joins do not bound the next lock.
  Explicit user `timeout=0` remains unlimited execution, not unlimited post-exit cleanup.
- Partial thread startup must preserve the original exception, release unowned
  resources, and detach any started reader before log scope unwinds.
- Normal parent exit must not trigger blind termination of intentional background
  tasks merely to force EOF. Cancel/timeout retains existing best-effort process
  tree termination, without an arbitrary-descendant termination guarantee.
- Incomplete capture and unconfirmed residual activity remain visible. Failed
  cleanup must prevent unsafe automatic retry through existing policy markers.
  Cancellation retains `cancelled=True` and non-retryable semantics.
- `extra['note']` alone is not proof of visibility: existing policy formatting
  only renders known flags. Prove the actual executor → engine → persistence →
  run-history consumer boundaries. A live stderr print alone is insufficient.
- No cross-process cancellation or unknown-commit reconciliation is implied.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Both streams reach EOF normally | Output captured, handles released, no new risk warning |
| Successful parent exits while descendant holds pipe | Bounded capture finish; parent success retained; capture/residual warning; no forced descendant termination |
| Late output after detachment | No new log/console write; reader eventually releases its pipe |
| Cancel or timeout with active readers | One reader per pipe; bounded cleanup; original outcome plus any residual warning |
| First or second reader fails to start | Original start error retained; no unstarted join; started readers detach safely |
| Read/write/flush fails | No uncaught reader exception; original outcome retained with capture diagnostic |
| Log write is already in flight during finish | No concurrent close; future writes revoked; safe close after ownership release |
| Success/cancelled record has policy risk | Persist and display risk without changing terminal status |
| Success/cancelled record has no risk | Existing text and classification unchanged |

## 5. Good / Base / Bad Cases

- Good: the direct process exits successfully, a surviving reader loses write
  permission, and the result explicitly says output capture is incomplete.
- Base: normal output is fully drained and both pipe/log owners release resources.
- Bad: `join(timeout)` is treated as evidence that a thread exited.
- Bad: a daemon reader is described as reaped merely because it cannot block
  interpreter shutdown.
- Bad: broad exception suppression hides late writes while ownership is unchanged.
- Bad: a clean history summary contradicts a persisted background-risk warning.

## 6. Tests Required

- `tests/test_executor_output_ownership.py`: real event-controlled reader threads,
  late output, concurrent-cleanup reader count, EOF handle release, read/write
  failures, partial starts, and in-flight write/close ownership for both executors.
  Assert reached points/effects outside executor-swallowed exception boundaries.
- `tests/test_executor_runtime_cleanup.py`, `tests/test_bat_executor.py`,
  `tests/test_executor_policies.py`: preserve cleanup, decoding/environment,
  cancellation and real Windows BAT smoke behavior. Update stale communicate
  fake expectations without removing outcome or bounded-cleanup assertions.
- `tests/test_output_diagnostic_projection.py`: known-risk success survives the
  real step/finish-step update boundary; ordinary success ignores arbitrary
  error text and note-only/false/unknown policy flags. These tests intercept
  `update_step_log`, so they do not by themselves prove a real database commit.
- `tests/test_executor_policies_engine.py`: unsafe failure is not retried and
  cancellation retains known background/orphan risk.
- Cross-layer acceptance must separately exercise actual capture, engine projection,
  isolated-database StepLog persistence, `get_step_log_summary_by_runs`, and history
  formatting. Do not replace the real persistence assertion with executor flags.
- `tests/test_ui_run_diagnostics.py`: known risk visible for success/cancelled;
  ordinary no-risk diagnostic wording unchanged.
- Run focused tests, then final full pytest and applicable quality gates against
  the frozen source. Attribute agent red/green evidence and mainline verification
  separately. Never reuse pre-change passing counts as new verification.

## 7. Wrong vs Correct

Wrong:

```python
reader.join(timeout=5)
log.close()  # A timed join does not establish reader completion.
proc.communicate(timeout=3)  # Competes with a dedicated reader.
```

Correct ownership sequence:

```text
wait for direct process outcome
join started readers with a finite budget
revoke future sink writes
close only sinks with no in-flight writer; defer others safely
report unfinished capture/residual activity
let each started reader release its own pipe
```

## Related contracts

- [Startup-stop ownership](./startup-stop-ownership.md): target identity before
  execution; it does not govern process output ownership.
- [Workflow-start progress](./workflow-start-progress.md): selected-step progress
  metadata, separate from output completeness.
