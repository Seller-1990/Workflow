# Workflow-start progress total

## 1. Scope / Trigger

Read when changing `workflow_started`, partial-run selection, or the UI/CLI
consumers of initial run progress. This contract covers the selected-step total,
not risk authorization or the general lifecycle state machine.

## 2. Signatures

- `WorkflowEngine.workflow_started = Signal(int, str, int)`:
  `(workflow_id, run_id, total_steps)`.
- `on_workflow_started(window, workflow_id, run_id, total: int = 0)`.
- CLI/import-run started callbacks accept the same third argument.
- `RunSignalPolicy` still controls whether nested runs emit outer UI signals.

## 3. Required and forbidden behavior

- Emit the engine's `len(selected_steps)` at workflow start, before executing
  the first step. The engine selection is authoritative for full, only-step,
  range, stage, and retry modes.
- Update every signal consumer together when changing its shape.
- UI passes a positive received total to `global_progress.show_running(total)`.
  A legacy direct callback without a total may use the existing placeholder 1;
  it must not replace a real received count with that placeholder.
- Do not infer partial-run totals from all workflow steps, or read an attribute
  that no producer assigns.
- Nested runs with suppressed run/progress signals must not reset outer progress.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Single selected step | Started total is 1 |
| Inclusive selected range | Started total equals the selected range length |
| Retry subset | Started total equals the retry-selected count |
| Slow first step | Correct total is available before its first completion |
| Legacy direct callback without total | Existing placeholder behavior, no exception |
| Nested signal policy suppresses run signals | No outer started/progress emission |

## 5. Good / Base / Bad Cases

- Good: selection happens once, and its actual length is sent with run identity.
- Base: full run reports all selected steps exactly as before.
- Bad: a one-step run initially displays the size of the full workflow.
- Bad: progress starts at 1 solely because `_running_step_total` was never assigned.

## 6. Tests Required

- `tests/test_run_step_total.py`: full/range/only/retry totals and nested policy.
- `tests/test_ui_run_lifecycle.py`: actual count reaches the progress panel and
  existing start/finish/unlock behavior remains.
- CLI, import-run, and full-suite tests must collect with the changed signal shape.

## 7. Wrong vs Correct

Wrong:

```python
engine.workflow_started.emit(workflow_id, run_id)
window.global_progress.show_running(len(all_workflow_steps))
```

Correct:

```python
engine.workflow_started.emit(workflow_id, run_id, len(selected_steps))
# In the UI signal consumer:
window.global_progress.show_running(total if total > 0 else 1)
```

## Related contracts

- [Path execution without redundant consent](./scoped-path-confirmation.md):
  legacy path-review state must not gate the selected execution snapshot.
- [Context curation](../context-curation.md): independently selectable contracts.
