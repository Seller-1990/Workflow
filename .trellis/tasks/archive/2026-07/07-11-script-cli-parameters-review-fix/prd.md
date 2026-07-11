# Review and Fix Script CLI Parameter Implementation

## Goal

Review the current script CLI temporary-parameter implementation, fix any confirmed issues, and verify the focused workflow tests pass.

## Scope

- Review the GUI run-argument collection path.
- Review run-time argument propagation through `WorkflowEngine` and `engine_core`.
- Review argument parsing and redaction helpers.
- Fix confirmed correctness/stability regressions directly.
- Do not introduce optional new features beyond the existing plan.

## Acceptance Criteria

- Previously failing `tests/test_executor_policies_engine.py` passes.
- Focused script CLI parameter tests pass.
- `python -m compileall src tests -q` passes.
- Temporary run arguments remain per-run only and are not written to workflow configuration.
- The implementation still avoids executing user scripts for argparse detection.

