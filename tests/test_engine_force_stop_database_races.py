"""Conditional force-stop persistence and real isolated SQLite races."""
from engine_core.force_stop import force_cancel_run_record


def test_force_cancel_run_record_marks_pending_run_cancelled():
    result = force_cancel_run_record(
        13,
        get_status=lambda run_id: "pending",
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=lambda *args, **kwargs: True,
        cancelled_status_value="cancelled",
    )

    assert result.status == "cancelled"
    assert result.existing_status == "pending"


def test_force_cancel_run_record_does_not_claim_terminal_after_concurrent_update():
    statuses = iter(("running", "failure"))

    result = force_cancel_run_record(
        14,
        get_status=lambda run_id: next(statuses),
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=lambda *args, **kwargs: None,
        cancelled_status_value="cancelled",
    )

    assert result.status == "already_terminal"
    assert result.existing_status == "failure"


def test_force_cancel_run_record_returns_not_found_for_missing_row():
    result = force_cancel_run_record(
        404,
        get_status=lambda run_id: None,
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=lambda *args, **kwargs: None,
        cancelled_status_value="cancelled",
    )

    assert result.status == "not_found"


def test_pending_force_cancel_uses_database_cas_and_preserves_normal_terminal(monkeypatch, tmp_path):
    from datetime import datetime

    import database_runs
    from _schema_guard_utils import _use_temp_database
    from models import RunHistory

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("pending 强制停止")
    pending = db.create_run_history(workflow.id)
    racing_terminal = db.create_run_history(workflow.id)
    real_update = database_runs.update_run_history

    def get_status(run_id):
        with db.get_session() as session:
            return session.query(RunHistory.status).filter(RunHistory.id == run_id).scalar()

    def concurrent_normal_completion(run_history_id, **kwargs):
        assert kwargs["_condition_status"] == ("pending", "running")
        with db.get_session() as session:
            row = session.query(RunHistory).filter(RunHistory.id == run_history_id).one()
            row.status = "success"
            row.end_time = datetime.now()
            session.commit()
        return real_update(run_history_id, **kwargs)

    cancelled = force_cancel_run_record(
        pending.id,
        get_status=get_status,
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=real_update,
        cancelled_status_value="cancelled",
    )
    raced = force_cancel_run_record(
        racing_terminal.id,
        get_status=get_status,
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=concurrent_normal_completion,
        cancelled_status_value="cancelled",
    )

    histories = {row.id: row for row in db.get_run_histories_by_workflow(workflow.id)}
    assert cancelled.status == "cancelled"
    assert histories[pending.id].status == "cancelled"
    assert raced.status == "already_terminal"
    assert raced.existing_status == "success"
    assert histories[racing_terminal.id].status == "success"
