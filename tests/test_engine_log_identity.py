"""Scheduling has a stable log key while executor retries update that one row."""
from pathlib import Path
from types import SimpleNamespace

from _schema_guard_utils import _use_temp_database
from engine import RunSignalPolicy, WorkflowEngine
from executors import ExecutorResult


def test_engine_begin_step_replay_and_business_retry_use_one_row(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("engine log key")
    step = db.create_step(workflow.id, "A", script_path="unused.py", order=1)
    db.update_step(step.id, retry_count=1)
    step = db.get_steps_by_workflow(workflow.id)[0]
    history = db.create_run_history(workflow.id)
    engine = WorkflowEngine()
    reached = []

    class Controlled:
        def execute(self, **kwargs):
            reached.append(kwargs)
            return ExecutorResult(success=len(reached) > 1, exit_code=0 if len(reached) > 1 else 1, error_message="first failure")

    monkeypatch.setattr("engine.get_executor", lambda *_args: Controlled())
    monkeypatch.setattr(engine, "_emit_log", lambda *_args: None)
    monkeypatch.setattr(engine, "_wait_before_retry", lambda *_args: False)
    try:
        first, _ = engine._begin_step_execution(step, history.id, tmp_path / "logs")
        second, _ = engine._begin_step_execution(step, history.id, tmp_path / "logs")
        assert first == second
        result = engine._execute_single_step(workflow, step, history.id, tmp_path / "logs", RunSignalPolicy(False, False, False, False, False))
        assert result.status == "success"
        assert len(reached) == 2
        logs = db.get_step_logs_by_run(history.id)
        assert len(logs) == 1
        assert logs[0].operation_key == f"step:{history.id}:{step.id}"
        assert logs[0].status == "success"
    finally:
        engine.shutdown()
        db.cleanup_session()
        db._engine.dispose()


def test_skip_replay_reuses_same_scheduled_identity(monkeypatch, tmp_path):
    import engine_core.lifecycle as lifecycle

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("skip log key")
    step = db.create_step(workflow.id, "A")
    history = db.create_run_history(workflow.id)
    one = lifecycle.record_skip_on_success(step=step, run_history_id=history.id)
    two = lifecycle.record_skip_on_success(step=step, run_history_id=history.id)
    assert one.step_log_id == two.step_log_id
    assert len(db.get_step_logs_by_run(history.id)) == 1
    db.cleanup_session()
    db._engine.dispose()
