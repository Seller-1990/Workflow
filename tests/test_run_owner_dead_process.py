"""A normally exited real process is a provably dead owner, not an expired lease."""
import multiprocessing
from pathlib import Path

from _schema_guard_utils import _use_temp_database
from database_process_identity import owner_liveness
import database_run_ownership as coordination
from database_coordination_models import RunOwner


def _publish_then_exit(db_path, workflow_id, step_id, messages):
    import database
    from database_process_identity import new_owner_identity
    from database_run_ownership import publish_owner

    database.DATABASE_PATH = Path(db_path)
    database.init_db()
    try:
        with publish_owner(new_owner_identity()):
            history = database.create_run_history(workflow_id)
        database.create_step_log(history.id, step_id)
        messages.put((history.id, history.run_id))
    finally:
        database.cleanup_session()
        database._engine.dispose()


def test_actual_exited_owner_can_be_recovered_without_signalling_pid(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKFLOW_APP_DATA_DIR", str(tmp_path / "child-app"))
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("dead real owner")
    step = db.create_step(workflow.id, "A")
    context = multiprocessing.get_context("spawn")
    messages = context.Queue()
    owner = context.Process(target=_publish_then_exit, args=(str(db.DATABASE_PATH), workflow.id, step.id, messages))
    owner.start()
    try:
        history_id, run_id = messages.get(timeout=12)
        owner.join(timeout=12)
        assert owner.exitcode == 0
        with db.get_fresh_session() as session:
            row = session.get(RunOwner, history_id)
            token = row.owner_token
            assert owner_liveness(row) == "dead"
            assert row.released_at is None
        assert coordination.request_run_stop(history_id).status == "orphaned"
        assert coordination.recover_orphaned_run(history_id, expected_run_id=run_id, expected_owner_token=token).status == "cancelled"
        assert db.get_step_logs_by_run(history_id)[0].status == "cancelled"
    finally:
        owner.join(timeout=12)
        messages.close()
        messages.join_thread()
        db.cleanup_session()
        db._engine.dispose()
        assert not owner.is_alive()
