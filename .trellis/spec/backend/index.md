# Backend specification router

## Scope and applicability

Backend, database, engine/executor, and their UI/CLI boundary contracts.

| When changing | Read |
|---|---|
| Imported script/cwd policy and legacy consent compatibility | [Path execution without redundant consent](./scoped-path-confirmation.md) |
| Visible desktop interval action and its run lock | [Visible range run](./visible-range-run.md) |
| Run-start signal or initial selected-step progress | [Workflow-start progress](./workflow-start-progress.md) |
| Run initialization or target-specific force-stop | [Startup-stop ownership](./startup-stop-ownership.md) |
| Python/BAT pipe readers, log closure, or incomplete-output diagnostics | [Executor output ownership](./executor-output-ownership.md) |
| Existing lifecycle, cancellation, run-state, or release contracts | [Legacy quality guidelines](./quality-guidelines.md) |
| StepLog creation retries or unknown commit outcomes | [StepLog creation identity](./step-log-idempotency.md) |
| Cross-process stop requests, owned runs or orphan recovery | [Persisted run ownership and cancellation](./run-ownership-cancellation.md) |
| CLI command construction and shutdown | [CLI engine lifetime](./cli-engine-lifetime.md) |
| Module organization | [Directory structure](./directory-structure.md) |
| Database/ORM conventions | [Database guidelines](./database-guidelines.md) |
| Error propagation | [Error handling](./error-handling.md) |
| Logging conventions | [Logging guidelines](./logging-guidelines.md) |
| Spec, Research, or task-manifest changes | [Context curation](../context-curation.md) |

The legacy quality document groups several pre-existing contracts; use it for
interactive discovery. Select independently applicable leaves and Research
`*-summary.md` files for task manifests, not this router or the legacy collection.

## Validation entry points

- Run the focused regression tests required by each selected contract.
- `python -B -m pytest -p no:cacheprovider -q`
- `python -B tools/check_requirements_consistency.py`
- `python -B tools/audit_broad_except.py`
- `python -B tools/audit_risky_calls.py`
- `python -B tools/module_hotspot_report.py --baseline quality/module_hotspot_baseline.json --fail-on-regression --max-lines 1000 --fail-on-threshold`
- `python -B tools/repo_hygiene.py --strict` (reports local runtime/cache residues too).
- `git diff --check`
