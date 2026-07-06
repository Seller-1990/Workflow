# Remaining Workflow Quality Optimizations

## Goal

Finish the remaining workflow optimization items discovered after the previous cancellation/stability work: restore CI quality gates, add targeted regression coverage, expose useful run diagnostics, and reduce selected maintenance hotspots without broad rewrites.

## Requirements

- Restore the module hotspot quality gate so CI passes on the current confirmed code shape.
- Keep the existing broad-exception and risky-call audit gates green.
- Update the workflow optimization document status so it no longer says "pending confirmation" after approval and implementation.
- Add regression coverage around workflow cancellation/stop behavior close to the orchestration boundary.
- Surface executor background-risk metadata in run-history diagnostics when available.
- Add lightweight scheduler execution counters that can be inspected by tests and future diagnostics.
- Add real pagination support for workflow run-history queries and UI loading.
- Continue small, behavior-preserving decomposition of `database_import_export.py` and `cli.py`.
- Avoid broad refactors, destructive operations, or unrelated behavior changes.

## Acceptance Criteria

- [x] `python tools/module_hotspot_report.py --top 30 --baseline quality/module_hotspot_baseline.json --fail-on-regression --max-lines 1000 --fail-on-threshold` passes.
- [x] `python tools/audit_broad_except.py` passes.
- [x] `python tools/audit_risky_calls.py` passes.
- [x] Focused tests cover cancellation, scheduler metrics, run-history pagination, and diagnostics.
- [x] Full pytest suite passes when feasible.
- [x] Trellis task state, docs, and spec learnings are updated as needed.

## Definition of Done

- Code changes are small, test-backed, and aligned with existing module boundaries.
- No silent fallbacks are added.
- No secrets or webhook tokens are exposed in exports or diagnostics.
- Hotspot baseline is updated only after verifying the current hotspot set is intentional or reduced.

## Technical Approach

- Treat hotspot baseline synchronization as a quality-gate maintenance fix, not as a reason for artificial line shaving.
- Prefer focused helper modules for extracted pure logic.
- Preserve compatibility facades for existing imports.
- Use offset/limit pagination as an additive API extension.
- Keep diagnostics read-only and derived from stored step-log/run-history data.

## Out of Scope

- Large UI redesign.
- Database schema changes unless an existing field already supports the needed behavior.
- Replacing the scheduler or executor architecture.
- Global dependency upgrades.

## Technical Notes

- User approved proceeding without further interruption unless destructive/external-risk operations appear.
- Current known failing gate: module hotspot baseline regressions.
- Existing specs read: `.trellis/spec/backend/index.md`, `quality-guidelines.md`, `database-guidelines.md`, `directory-structure.md`, and shared guides.
