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
  step logs for that run.
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
- Header state transitions must be exception-free for
  `running -> idle/cancelled/failure`; otherwise finish handling can abort
  before `refresh_run_lock_panels()` unlocks step actions.

#### 4. Validation & Error Matrix

- Running false, stopping false -> idle/run-enabled state.
- Running true, stopping false -> running/stop-enabled state.
- Running true or false, stopping true -> stopping state.
- Running state has created pulse animation -> idle transition stops the
  animation without raising and leaves step panels enabled.

#### 5. Good/Base/Bad Cases

- Good: theme refresh and state refresh use the same projection.
- Bad: one UI path checks `_running`, another checks `_stopping_in_progress`,
  and the button label drifts.

#### 6. Tests Required

- Pure `ui.run_state` tests for every projection combination.
- UI lifecycle test for `workflow_finished` after a pulse animation has started.

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

### Scenario: PyInstaller Release Packaging

#### 1. Scope / Trigger

- Trigger: changing `.spec`, release requirements, or package workflows.
- Scope: Windows `build_slim2.spec` and macOS Intel packaging workflow.

#### 2. Signatures

- Windows: `python -m PyInstaller build_slim2.spec --noconfirm`
- macOS Intel: `pyinstaller build_macos_intel.spec --noconfirm`
- Smoke gate: packaged executable/app binary must accept `--self-check`.

#### 3. Contracts

- `certifi` data files must be collected so HTTPS trust works in frozen apps.
- Python `< 3.12` packages using `pkg_resources` must include `backports.tarfile`.
- Windows-only dependencies must use platform markers in requirement files and
  must not be hidden-imported by the macOS spec.
- macOS Intel builds must run on an Intel runner/host, not from Windows.

#### 4. Validation & Error Matrix

- Missing `backports.tarfile` -> frozen startup can fail in `pyi_rth_pkgres.py`.
- Missing `certifi` data -> HTTPS checks may use a nonexistent CA bundle.
- Installing `pywin32` on macOS -> dependency install fails before packaging.
- Cross-building macOS from Windows -> reject as unsupported; use macOS runner.

#### 5. Good/Base/Bad Cases

- Good: package build passes, `--self-check` passes, and hash artifact is emitted.
- Base: source tests pass but package smoke has not run; do not call it releasable.
- Bad: assuming PyInstaller warnings are harmless after a frozen startup failure.

#### 6. Tests Required

- Focused workflow/dependency manifest tests for requirements/workflow changes.
- Full pytest before release commits when package workflow or requirements change.
- Packaged `--self-check` for each produced platform artifact.

#### 7. Wrong vs Correct

Wrong:

```python
hiddenimports=["requests", "watchdog"]
```

Correct:

```python
hiddenimports=["requests", "watchdog", "backports.tarfile"]
```

### Scenario: Release Metadata and Artifact Hygiene

#### 1. Scope / Trigger

- Trigger: changing app version, release docs, `.gitignore`, packaging specs, or
  generated artifacts under `dist/`.

#### 2. Signatures

- Version source: `src/config.py::APP_VERSION`
- Package metadata mirror: `src/__init__.py::__version__`
- Artifact examples: `dist/工作流管理_<APP_VERSION>_slim2.exe`

#### 3. Contracts

- `APP_VERSION` is the release version source of truth.
- `src/__init__.py::__version__` and README current-version text must match
  `APP_VERSION`.
- PyInstaller spec comments and README output examples must use
  `<APP_VERSION>` placeholders instead of hard-coded historical versions.
- `dist/` artifacts are ignored by Git; release binaries are delivered through
  GitHub Actions artifacts, not committed to the repository.

#### 4. Validation & Error Matrix

- README says an older current version -> release metadata test fails.
- Spec comment contains `工作流管理_<number>` -> release metadata test fails.
- `.gitignore` re-allows `dist/*.exe` -> release metadata test fails.

#### 5. Good/Base/Bad Cases

- Good: bump `APP_VERSION`, mirror `__version__`, update README current version.
- Base: pure rebuild from unchanged source keeps the same version.
- Bad: committing `dist/*.exe` or `.sha256` files to satisfy delivery needs.

#### 6. Tests Required

- `tests/test_release_metadata.py` must cover version consistency, spec
  placeholders, and `dist/` ignore behavior.

#### 7. Wrong vs Correct

Wrong:

```text
输出: dist/工作流管理_4.1.0_slim2.exe
```

Correct:

```text
输出: dist/工作流管理_<APP_VERSION>_slim2.exe
```

### Scenario: Run Finalization StepLog Convergence

#### 1. Scope / Trigger

- Trigger: changing run finalization, `RunHistory` terminal writes, or StepLog
  bulk cleanup.
- Scope: `engine_core.run_finalization.finalize_run_record`,
  `engine_core.lifecycle.finalize_run`, and `database_runs` StepLog updates.

#### 2. Signatures

- `finalize_run_record(..., finish_unfinished_step_logs=..., update_run_history=...) -> bool`
- `finish_unfinished_step_logs(run_history_id: int, status: str, error_message: str) -> int`

#### 3. Contracts

- Before writing any terminal `RunHistory.status`, all pending/running StepLog
  rows for the run must be moved to a terminal status.
- `cancelled` runs converge unfinished steps to `cancelled`.
- `failure` runs converge unfinished steps to `failure`.
- Unexpected `success` runs with unfinished steps converge them to `skipped`,
  never to false success.
- StepLog `error_message` is truncated at the database write boundary.

#### 4. Validation & Error Matrix

- Step cleanup fails with operational error -> warn and still attempt run
  terminal update.
- Run terminal update fails with operational error -> return `False` to caller.
- Programming errors such as invalid update fields must propagate, not be hidden
  as ordinary finalization failures.

#### 5. Good/Base/Bad Cases

- Good: terminal run and all related StepLog rows are terminal in one ordered
  finalization flow.
- Base: no unfinished StepLog rows; bulk update affects zero rows.
- Bad: `RunHistory.status="failure"` while a related StepLog remains
  `running` or `pending`.

#### 6. Tests Required

- Pure finalization tests assert step cleanup happens before run terminal write.
- Database contract tests assert long StepLog errors are truncated.

#### 7. Wrong vs Correct

Wrong:

```python
update_run_history(run_id, status="failure", end_time=end_time)
```

Correct:

```python
finish_unfinished_step_logs(run_id, "failure", "运行失败，未完成步骤被清理")
update_run_history(run_id, status="failure", end_time=end_time)
```

### Scenario: Run History Latest Ordering

#### 1. Scope / Trigger

- Trigger: changing run-history queries, latest-run helpers, or history-panel
  pagination.
- Scope: `database_runs.get_run_histories_by_workflow` and
  `database_runs.get_latest_run_history`.

#### 2. Signatures

- `get_run_histories_by_workflow(workflow_id: int, limit: int = 20, offset: int = 0) -> list[RunHistory]`
- `get_latest_run_history(..., only_finished: bool = False, exclude_run_history_id: int | None = None) -> RunHistory | None`

#### 3. Contracts

- "Latest" means the most recently inserted `RunHistory` row, ordered by
  `RunHistory.id DESC`.
- Do not order latest-history queries by `start_time`; host clock changes,
  delayed writes, or repaired timestamps can make a newer row appear older.
- Pagination offsets must apply after the `id DESC` ordering.
- `only_finished` and `exclude_run_history_id` filters must not change the
  ordering contract.

#### 4. Validation & Error Matrix

- Newer row has an earlier `start_time` -> newer row still appears first.
- `start_time` is repaired or imported -> insertion order still determines
  latest UI display.
- No matching rows -> return an empty list or `None` as before.

#### 5. Tests Required

- Database contract test where two rows have inverted `start_time` values and
  the higher `id` is returned first.
- Latest-helper test with `only_finished=True` and inverted timestamps.

#### 6. Wrong vs Correct

Wrong:

```python
query.order_by(RunHistory.start_time.desc(), RunHistory.id.desc())
```

Correct:

```python
query.order_by(RunHistory.id.desc())
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

### Scenario: Scheduler Metrics and Diagnostics

#### 1. Scope / Trigger

- Trigger: changing `engine_core.scheduler.run_steps_parallel` or parallel
  execution diagnostics.

#### 2. Signatures

- `SchedulerMetrics(submitted=0, completed=0, cancelled=0, failed=0)`
- `run_steps_parallel(..., metrics: SchedulerMetrics | None = None) -> list`

#### 3. Contracts

- Metrics are additive diagnostics only; they must not change scheduler return
  shape or step-result ordering.
- `submitted` increments only when a future is actually submitted.
- `completed` increments when a future result is harvested, including
  exception-to-result conversion through `on_exception`.
- `cancelled` increments only for futures that `Future.cancel()` reports as
  cancelled or that are observed as cancelled.

#### 4. Tests Required

- Cancellation-before-submission test asserts zero submissions.
- Stop-after-in-flight test asserts no extra submissions after cancellation.
- Exception conversion test asserts `failed` and `completed` counters.

### Scenario: Executor Policy Risk Visibility

#### 1. Scope / Trigger

- Trigger: changing non-retryable executor results, `ExecutorResult.extra`, run
  history summaries, or run-history diagnostics.

#### 2. Contracts

- `manual_required`, `background_risk`, and `orphan_risk` must remain visible
  after execution by appending stable diagnostic text to the step log error
  message.
- Run-history summary counters may derive from that stable text, but must not
  expose secrets or raw webhook URLs.
- Failure diagnostics should prefer user-actionable text such as "需要人工确认"
  and "可能仍有后台任务".

#### 3. Tests Required

- Executor policy test asserts the step result error message contains the risk
  note.
- Pure run-diagnostic test asserts background/manual/orphan risk counts appear
  in user-facing diagnostic text.

---

## Code Review Checklist

<!-- What reviewers should check -->

For workflow execution changes, reviewers should check:

- Cancellation does not submit new work after the stop signal.
- In-flight work is not abandoned without step-log cleanup.
- Progress counts actual completed/harvested results after cancellation.
