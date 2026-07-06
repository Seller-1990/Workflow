# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Backend changes should preserve workflow lifecycle invariants first: cancellation
must propagate, terminal run state must match step logs, and UI/CLI status text
must not imply success while work is still stopping.

---

## Forbidden Patterns

- Do not hide cancellation as a generic failure.
- Do not update terminal `RunHistory` status before cleaning pending/running
  step logs for a cancelled run.
- Do not duplicate run-state button logic outside `ui.run_state`.
- Do not add schema objects only to ORM models without an idempotent migration.

---

## Required Patterns

### Scenario: Executor Cancellation Result Contract

#### 1. Scope / Trigger

- Trigger: changing Python, Excel, Power BI, or sub-workflow executors.
- Scope: every executor returning a user-cancelled result.

#### 2. Signatures

- `ExecutorResult(success=False, exit_code=-1, error_message="用户取消", extra=...)`
- `build_cancelled_extra(note="用户取消") -> dict`

#### 3. Contracts

- User cancellation must be explicit in `extra["cancelled"] == True`.
- Cancellation should also be non-retryable through the shared result policy
  fields so retry logic does not treat it like a transient execution failure.
- External executors that may leave background work must add explicit risk
  fields rather than hiding the uncertainty.

#### 4. Validation & Error Matrix

- Python process receives cancellation -> return cancelled result and cleanup.
- Excel cancellation before or during run -> return `exit_code=-1` with cancelled extra.
- Power BI startup / REST / auto-close wait cancellation -> return cancelled extra.
- Sub-workflow cancellation or grace-period expiry -> return cancelled extra.

#### 5. Good/Base/Bad Cases

- Good: `extra` contains both cancellation and retry-policy markers.
- Base: non-cancelled failures keep their existing failure classification.
- Bad: returning only `success=False` with a generic error string; callers cannot
  distinguish stop requests from execution failures.

#### 6. Tests Required

- Executor policy tests must assert `extra["cancelled"] is True`.
- Runtime cleanup tests must still assert process/application cleanup behavior.

#### 7. Wrong vs Correct

Wrong:

```python
return ExecutorResult(False, -1, "用户取消")
```

Correct:

```python
return ExecutorResult(
    success=False,
    exit_code=-1,
    error_message="用户取消",
    extra=build_cancelled_extra(),
)
```

### Scenario: UI Run-State Projection

#### 1. Scope / Trigger

- Trigger: changing run/stop buttons, header status, or running/stopping labels.

#### 2. Signatures

- `compute_header_run_state(engine_running: bool, stopping: bool) -> str`

#### 3. Contracts

- Header controls must be derived from the projection helper rather than
  duplicating local boolean logic.
- `stopping=True` wins over ordinary running state for user-facing labels.

#### 4. Validation & Error Matrix

- Running false, stopping false -> idle/run-enabled state.
- Running true, stopping false -> running/stop-enabled state.
- Running true or false, stopping true -> stopping state.

#### 5. Good/Base/Bad Cases

- Good: theme refresh and state refresh use the same projection.
- Bad: one UI path checks `_running`, another checks `_stopping_in_progress`,
  and the button label drifts.

#### 6. Tests Required

- Pure `ui.run_state` tests for every projection combination.

#### 7. Wrong vs Correct

Wrong:

```python
button.setText("停止" if engine_running else "运行")
```

Correct:

```python
state = compute_header_run_state(engine_running, stopping)
set_header_run_button_state(window, state)
```

### Scenario: Masked Export Secret Guard

#### 1. Scope / Trigger

- Trigger: changing workflow JSON export, webhook serialization, or notification config export.

#### 2. Signatures

- `assert_no_plain_webhook_secrets(payload: object) -> None`
- `export_to_json_impl(..., include_secrets: bool = False) -> int`

#### 3. Contracts

- Default exports (`include_secrets=False`) must not contain plain strings with
  `access_token=`.
- Masked webhook placeholders are allowed only as
  `__WORKFLOW_WEBHOOK_URL_MASKED__`.
- The payload-level guard must run after assembling export data and before
  writing the JSON file.

#### 4. Validation & Error Matrix

- Masked webhook URL -> export allowed.
- Plain webhook URL in any nested exported string -> raise `ValueError`.
- `include_secrets=True` -> explicit secret export path, guard is skipped.

#### 5. Good/Base/Bad Cases

- Good: local field masking plus final payload scan.
- Base: exports with no webhooks pass unchanged.
- Bad: adding a new notification field that bypasses masking and writes a plain
  webhook URL.

#### 6. Tests Required

- Pure guard test for nested payload leaks.
- Export test proving default JSON output does not include secret tokens.

#### 7. Wrong vs Correct

Wrong:

```python
json.dump(data, f, ensure_ascii=False, indent=2)
```

Correct:

```python
if not include_secrets:
    assert_no_plain_webhook_secrets(data)
json.dump(data, f, ensure_ascii=False, indent=2)
```

---

## Testing Requirements

Prefer pure tests for extracted contracts, then heavier Qt/database/executor
tests where local dependencies are available.

### Scenario: Workflow Cancellation in Parallel Scheduling

#### 1. Scope / Trigger

- Trigger: changing workflow scheduling, cancellation propagation, or step execution.
- Scope: `engine_core.scheduler.run_steps_parallel`, `engine_core.step_execution.execute_parallel_steps`, and `engine_core.run_orchestration.execute_steps`.

#### 2. Signatures

- `run_steps_parallel(..., should_stop: Optional[Callable[[], bool]] = None) -> list`
- `execute_parallel_steps(..., run_cancel_event: threading.Event | None = None) -> list[StepResult]`

#### 3. Contracts

- `should_stop()` returning `True` means no new steps may be submitted.
- Futures already running must still be awaited and harvested so their step logs can finish cleanly.
- Futures not yet started should be cancelled with `Future.cancel()` when possible.
- `execute_steps` must count actual returned results, not the original batch size, after a cancellation shortens a batch.

#### 4. Validation & Error Matrix

- Cancel before first submission -> return `[]`; no step runner is called.
- Cancel after one future completes -> stop submitting further steps; wait for in-flight futures.
- Cancelled step result -> orchestration returns failure-like `False`, and final run status resolves to `cancelled`.
- Step runner exception -> use `on_exception` if provided; otherwise re-raise as before.

#### 5. Good/Base/Bad Cases

- Good: a batch of four steps with two in flight cancels after step 1; steps 1 and 2 finish as cancelled; steps 3 and 4 never start.
- Base: no cancellation; sliding-window behavior and result ordering remain unchanged.
- Bad: clearing the future map immediately on cancel. That can finalize RunHistory while an in-flight StepLog is still running.

#### 6. Tests Required

- Scheduler unit test: cancellation before submission starts no steps.
- Scheduler unit test: cancellation stops new submissions but waits for in-flight steps.
- Engine-level test: `_execute_parallel_steps` passes cancellation state into the scheduler.

#### 7. Wrong vs Correct

Wrong:

```python
if should_stop():
    futures.clear()
    break
```

Correct:

```python
if should_stop():
    stop_submitting = True
    cancel_not_started(futures)
```

The correct version stops new submissions without dropping already-running step futures.

---

## Code Review Checklist

<!-- What reviewers should check -->

For workflow execution changes, reviewers should check:

- Cancellation does not submit new work after the stop signal.
- In-flight work is not abandoned without step-log cleanup.
- Progress counts actual completed/harvested results after cancellation.
