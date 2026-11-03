# Startup force-stop ownership

## 1. Scope / Trigger

Read when changing RunHistory creation, engine active-run registration, initialization
failure handling, or target-specific force-stop. This is one contract: stopping a
history ID must not cancel a different live run, including during startup.

## 2. Signatures

- `WorkflowEngine.force_stop_run(run_history_id: int)`.
- `engine_core.lifecycle.begin_run(..., create_run_history_fn=None) -> RunContext`.
  The default uses the existing database creation helper; engine orchestration
  supplies the creation-and-registration function.
- `BeginRunError.context: RunContext` carries the already-created history identity.
- `RunContext.run_history_id`, `run_id`, and `log_dir` identify initialization
  work that outer finalization must retain even if startup fails.

## 3. Required and forbidden behavior

- Treat the requested RunHistory ID as the target, not as a generic stop-current
  command. Use `cancel()` for an unqualified current-engine cancellation.
- Live ownership requires explicit membership in the engine's registered active
  IDs. An empty activity set or a missing current ID is not ownership evidence.
- RunHistory creation and registration of its actual ID share `engine._lock`,
  also used by `force_stop_run`. This closes the same-engine commit-to-registration
  window; directory/running-state setup stays outside that lock.
- Preserve the created identity locally for finalization even if initialization
  fails. `BeginRunError` carries the normal post-creation failure context.
- The lock can delay same-engine stop/status access while database creation is
  blocked. Do not claim this makes database creation non-blocking or coordinates
  another process that edits RunHistory directly.
- A matching active target propagates cancellation before step side effects.
  An unrelated historical target uses orphan-record cleanup and must not set
  the live engine's cancellation flag.
- Cleanup pending/running StepLogs before writing an orphan RunHistory terminal
  state; preserve a concurrent normal terminal result via conditional update.
- Remove registered IDs on success, cancellation, and initialization failure.
  Preserve nested-run and outer-context restoration semantics.
- Do not repair a missed-registration race by cancelling every requested ID
  while the engine is starting.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Matching live ID is stopped during initialization | Cancellation observed before steps; actual run reaches cancelled finalization |
| Historical B is stopped while A initializes | B is cleaned; A is not cancelled and can execute |
| No live ownership is established | Do not infer identity from an empty set |
| mkdir/running-state update fails after history creation | Finalize the created ID and remove active registration |
| Orphan becomes normally terminal concurrently | Do not overwrite that terminal status |
| Nested active ID is targeted | Existing shared-engine cancellation propagation remains |

## 5. Good / Base / Bad Cases

- Good: bind the actual created ID to the run lifecycle, then accept target-specific
  cancellation for that ID.
- Base: an idle engine cleans an orphan without affecting an unrelated future run.
- Bad: `_running and not _active_run_ids` implies every requested ID is current.
- Bad: a cancellation regression passes only because unrelated setup raised first.

## 6. Tests Required

- `tests/test_engine_force_stop_run.py`: active, orphan, idle, and empty-startup
  predicates; unrelated targets never set the cancellation flag.
- `tests/test_comprehensive_review_regressions.py`: same/different-target startup
  scenarios with an isolated DB and external reached-branch assertions.
- `tests/test_run_initialization_finalization.py`: directory/update failures retain
  the created history ID, reach terminal failure, and clear active ownership.
- Preserve range, selected totals, and nested R5 executor-policy tests.
- For engine APIs that catch exceptions and return False, assert a cause-specific
  effect or reached point outside the caught block. False alone does not prove
  the intended rejection/cancellation branch ran.

## 7. Wrong vs Correct

Wrong:

```python
if engine._running and not engine._active_run_ids:
    engine._cancelled = True
```

Correct target predicate after explicit lifecycle registration:

```python
if engine._running and run_history_id in engine._active_run_ids:
    engine._cancelled = True
else:
    # Clean only the requested orphan record; do not cancel another live run.
    clean_orphan_record(run_history_id)
```

## Related contracts

- [Scoped path confirmation](./scoped-path-confirmation.md): execute only checked data.
- [Workflow-start progress](./workflow-start-progress.md): publish selected metadata.
