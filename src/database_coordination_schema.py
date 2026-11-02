"""Restartable additive migrations for keyed logs and local run coordination."""
from sqlalchemy import text

from database_coordination_models import RunOwner, RunStopRequest


def _migrate_v12_step_log_operation_identity(engine):
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(step_logs)"))}
        if "operation_key" not in columns:
            connection.execute(text("ALTER TABLE step_logs ADD COLUMN operation_key VARCHAR(128)"))
        if "creation_payload" not in columns:
            connection.execute(text("ALTER TABLE step_logs ADD COLUMN creation_payload TEXT"))
        # NULL keys deliberately keep every legacy row, including duplicate pairs.
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_step_logs_operation_key ON step_logs(operation_key)"
        ))


def _migrate_v13_run_ownership(engine):
    RunOwner.__table__.create(engine, checkfirst=True)
    RunStopRequest.__table__.create(engine, checkfirst=True)
