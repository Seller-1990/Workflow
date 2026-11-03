"""SQLite uniqueness arbitrates real independent log creators, not Python locks."""
import multiprocessing
from pathlib import Path

from _schema_guard_utils import _use_temp_database


def _create(db_path, history_id, step_id, note, start, results):
    import database

    database.DATABASE_PATH = Path(db_path)
    database.init_db()
    try:
        if not start.wait(8):
            results.put(("timeout", None))
            return
        try:
            row = database.create_step_log(history_id, step_id, error_message=note, operation_key="shared-process-key")
            results.put(("created", row.id))
        except ValueError as error:
            results.put(("conflict", str(error)))
    finally:
        database.cleanup_session()
        database._engine.dispose()


def test_concurrent_process_replay_and_payload_conflict(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKFLOW_APP_DATA_DIR", str(tmp_path / "isolated-child-app"))
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("multiprocess log")
    step = db.create_step(workflow.id, "A")
    history = db.create_run_history(workflow.id)
    context = multiprocessing.get_context("spawn")
    start, results = context.Event(), context.Queue()
    workers = [context.Process(target=_create, args=(str(db.DATABASE_PATH), history.id, step.id, "same", start, results)) for _ in range(2)]
    for worker in workers:
        worker.start()
    start.set()
    try:
        outcomes = [results.get(timeout=12) for _ in workers]
        assert outcomes[0] == outcomes[1]
        assert outcomes[0][0] == "created"
        assert len(db.get_step_logs_by_run(history.id)) == 1
        conflict = context.Process(target=_create, args=(str(db.DATABASE_PATH), history.id, step.id, "different", start, results))
        workers.append(conflict)
        conflict.start()
        assert results.get(timeout=12)[0] == "conflict"
        assert len(db.get_step_logs_by_run(history.id)) == 1
    finally:
        start.set()
        for worker in workers:
            worker.join(timeout=12)
        results.close()
        results.join_thread()
        db.cleanup_session()
        db._engine.dispose()
        assert all(worker.exitcode == 0 for worker in workers)
