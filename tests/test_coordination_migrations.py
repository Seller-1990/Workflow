"""Only isolated v11-shaped databases, including interrupted additive upgrades."""
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError

import database


def _legacy_database(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE run_histories (id INTEGER PRIMARY KEY, run_id TEXT)")
        connection.exec_driver_sql("INSERT INTO run_histories VALUES (7, 'legacy-run')")
        connection.exec_driver_sql(
            'CREATE TABLE step_logs (id INTEGER PRIMARY KEY, run_history_id INTEGER, step_id INTEGER, "order" INTEGER, error_message TEXT)'
        )
        connection.exec_driver_sql("INSERT INTO step_logs VALUES (1,7,2,1,'first'),(2,7,2,1,'duplicate retained')")
    database._ensure_schema_version_table(engine)
    for version in range(1, 12):
        database._record_version(engine, version)
    return engine


def test_upgrade_retains_duplicates_and_restart_is_idempotent(monkeypatch, tmp_path):
    path = tmp_path / "legacy.db"
    engine = _legacy_database(path)
    monkeypatch.setattr(database, "DATABASE_PATH", path)
    database._run_pending_migrations(engine)
    database._run_pending_migrations(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id,error_message,operation_key FROM step_logs ORDER BY id")).all() == [
            (1, "first", None), (2, "duplicate retained", None),
        ]
        assert connection.execute(text("SELECT MAX(version) FROM schema_versions")).scalar() == 13
        tables = set(connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars())
        assert {"run_owners", "run_stop_requests"} <= tables
        connection.exec_driver_sql("INSERT INTO step_logs(id,operation_key) VALUES (3,'unique-key')")
        with pytest.raises(IntegrityError) as error:
            connection.exec_driver_sql("INSERT INTO step_logs(id,operation_key) VALUES (4,'unique-key')")
        assert "UNIQUE" in str(error.value)
    backups = list((tmp_path / "migration_backups").glob("*.db"))
    assert len(backups) == 1
    snapshot = create_engine(f"sqlite:///{backups[0]}")
    with snapshot.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM step_logs")).scalar() == 2
    snapshot.dispose()
    engine.dispose()


@pytest.mark.parametrize("failure_sql", ("ADD COLUMN creation_payload", "CREATE UNIQUE INDEX", "CREATE TABLE run_stop_requests"))
def test_interrupted_additive_migration_recovers_without_deleting_rows(monkeypatch, tmp_path, failure_sql):
    path = tmp_path / "interrupted.db"
    engine = _legacy_database(path)
    monkeypatch.setattr(database, "DATABASE_PATH", path)
    reached = []

    def fail_once(connection, cursor, statement, parameters, context, many):
        normalized = " ".join(statement.split())
        if failure_sql in normalized and not reached:
            reached.append(normalized)
            raise RuntimeError("injected migration interruption")

    event.listen(engine, "before_cursor_execute", fail_once)
    with pytest.raises(RuntimeError, match="schema 迁移"):
        database._run_pending_migrations(engine)
    assert len(reached) == 1
    event.remove(engine, "before_cursor_execute", fail_once)
    database._run_pending_migrations(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM step_logs")).scalar() == 2
        assert connection.execute(text("SELECT MAX(version) FROM schema_versions")).scalar() == 13
        assert {"operation_key", "creation_payload"} <= {
            row[1] for row in connection.execute(text("PRAGMA table_info(step_logs)"))
        }
    assert all(item.parent == tmp_path / "migration_backups" for item in (tmp_path / "migration_backups").glob("*.db"))
    engine.dispose()
