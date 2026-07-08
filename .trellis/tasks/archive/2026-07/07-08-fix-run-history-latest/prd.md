# PRD: Fix Latest Run History Visibility

## Goal

Fix the issue where the run history view does not show the latest history record after workflow execution.

## What I Already Know

- The user observes that the newest run history is missing from the run history UI.
- Recent changes touched run finalization and StepLog cleanup, so finalization/query ordering is a likely area to verify.
- Existing user report `docs/10_多角度代码审查报告_2026-07-07.md` is untracked and must be left untouched.

## Requirements

- Reproduce the missing-latest-history symptom with a focused test or harness.
- Fix the smallest confirmed cause in the write/query/refresh chain.
- Preserve run finalization and StepLog convergence invariants.

## Acceptance Criteria

- Latest finished run appears first in run history queries and UI-facing data.
- Regression test covers the issue.
- Focused tests and quality gates pass.

## Technical Notes

- Applicable specs: `.trellis/spec/backend/index.md`, `.trellis/spec/backend/quality-guidelines.md`.
