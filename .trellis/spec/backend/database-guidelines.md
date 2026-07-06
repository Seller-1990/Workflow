# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

The project uses SQLAlchemy ORM over SQLite. `src/database.py` owns engine
initialization, schema migrations, and the compatibility facade; domain CRUD is
split into modules such as `database_runs.py`, `database_workflows.py`, and
`database_import_export.py`.

Callers should import through `database.py` unless they are inside the database
layer. New implementation logic should live in the focused database module, then
be re-exported by the facade when existing callers need the function.

---

## Query Patterns

### Run History and Step Logs

Use the existing run-history helpers instead of open-coded queries:

- `get_run_histories_by_workflow(workflow_id, limit=100, offset=0)` for
  paginated history lists. UI callers should request `page_size + 1` rows to
  decide whether a "load more" affordance is needed.
- `get_step_logs_by_run(run_history_id)` for detail rows ordered by `StepLog.order`.
- `get_step_log_summary_by_runs(run_history_ids)` for history-list summaries,
  including risk counters derived from stored step-log diagnostic text:
  `manual_required`, `background_risk`, and `orphan_risk`.
- `get_recent_step_logs_for_step(workflow_id, step_id, limit=20)` when looking up
  recent logs for one step.

Do not loop over run histories and query step logs one run at a time. Use the
batch summary/helper APIs to avoid N+1 database reads in UI refresh paths.

When adding executor policy diagnostics, keep storage additive: append stable
diagnostic text to `StepLog.error_message`, then derive summary counters through
the shared run-policy note helper. Do not add a schema column for a diagnostic
unless multiple workflows need structured querying.

### Terminal State Updates

For normal workflow completion, use `engine_core.run_finalization.finalize_run_record`.
When status is `cancelled`, it must cancel pending/running `StepLog` rows before
writing the `RunHistory` terminal status. This keeps visible history and step
details consistent.

---

## Migrations

Register every schema migration in `SCHEMA_MIGRATIONS` and implement an
idempotent `_migrate_vN_name(engine)` function in `database.py`.

Required behavior:

- New databases get the schema through `Base.metadata.create_all`.
- Existing databases get additive changes through migration functions.
- Use `CREATE INDEX IF NOT EXISTS` for index migrations.
- Record success through `schema_versions`; a failed migration must raise and
  stop startup rather than allowing writes against a half-upgraded schema.

Example:

```python
SCHEMA_MIGRATIONS = [
    (8, "_migrate_v8_run_history_step_log_perf_indexes"),
]

def _migrate_v8_run_history_step_log_perf_indexes(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_step_logs_run_order "
            "ON step_logs(run_history_id, \"order\")"
        ))
```

---

## Naming Conventions

Index names use `ix_<table>_<columns>` for non-unique indexes and
`uq_<table>_<columns>` for unique indexes.

Indexes that support existing hot paths:

- `ix_run_histories_wf_status_time`: workflow + status + time filters.
- `ix_run_histories_wf_endtime`: finished-run lookups.
- `ix_run_histories_wf_start_id`: history list and latest-run ordering.
- `ix_step_logs_run_status`: cancellation cleanup by run/status.
- `ix_step_logs_run_order`: detail rows by run ordered by step order.
- `ix_step_logs_step_run`: recent logs for one step.

---

## Common Mistakes

### Missing the Migration Half of a Model Change

Wrong: add an `Index(...)` to `models.py` only.

Correct: add the ORM index and an idempotent migration for existing databases,
then cover both with tests.

### Finalizing Runs Before Step Logs

Wrong: write `RunHistory.status = "cancelled"` while related `StepLog` rows are
still `pending` or `running`.

Correct: cancel pending/running step logs first, then write the run terminal
status through `finalize_run_record`.
