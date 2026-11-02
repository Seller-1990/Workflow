# Visible range-run entry point

## Applicability

Read when changing the desktop range-run action, the compilation/plan toolbar,
range selection dialog or its interaction with run locks.

## Required behavior

- The range action must be in a visible area of the active planning page, in both
  stage and list views; the hidden legacy RunControlPanel is not a usable entry.
- Reuse `run_control.btn_run_range` in the plan switch bar. Keep its existing
  clicked signal, `run_requested("step_range", None)`, selected-step default,
  theme update and `set_running` lock. Do not duplicate the mode implementation.
- Choosing start/end opens the existing StepRangeDialog and executes the engine's
  global ordered interval including both endpoints, including across stages.
- Reverse endpoints retain the existing automatic swap behavior and count hint.
- Dialog cancellation must not start a worker or create a run.
- Execution mode/arguments and actual progress total must use the same interval.

## Forbidden behavior

- A test that finds the button object but never verifies effective visibility.
- A second button with independent lock state or a new interval selector that
  diverges from the engine.
- Claiming native desktop acceptance from an offscreen layout test alone.

## Required validation

- `tests/test_ui_visible_range_run.py`: hidden old panel, visible reparented
  button, signal dispatch and running/idle lock transitions.
- `tests/test_step_range_run.py`: inclusive, reversed, cross-stage and invalid
  endpoints; existing dialog cancel/run dispatch.
- Native isolated desktop: visibly open the dialog, cancel once, then run a safe
  selected interval and verify only its steps in isolated run logs.

## Related contracts

- [Workflow-start progress](./workflow-start-progress.md)
- [Path execution without redundant consent](./scoped-path-confirmation.md)
