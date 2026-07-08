# PRD: Fix Step Run Actions After Single-Step Execution

## Goal

Fix the issue where, after running a single step, all step actions such as
"run only this step" and "run from this step" remain unavailable until the user
switches workflows.

## What I Know

- The symptom is UI state-related: switching workflows restores the actions,
  which suggests selection/action enablement is not refreshed after the run
  lifecycle returns to idle.
- The fix should preserve run-state button contracts and avoid duplicating
  run-state logic.
- The existing untracked report under `docs/` must remain untouched.

## Requirements

- Reproduce the disabled-action state with a focused UI/unit test where possible.
- Identify the state refresh path after single-step execution finishes.
- Re-enable step contextual actions when the engine returns to idle and a valid
  step remains selected.
- Preserve disabled behavior while the workflow is actively running or stopping.

## Acceptance Criteria

- After a single-step run finishes, step actions are available for the selected
  step without switching workflows.
- A regression test covers the refresh path.
- Focused tests and project quality gates pass.

## Technical Notes

- Applicable specs: `.trellis/spec/backend/index.md`,
  `.trellis/spec/backend/quality-guidelines.md`,
  `.trellis/spec/guides/index.md`.
