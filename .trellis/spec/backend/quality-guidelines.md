# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

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
