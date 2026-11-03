"""Real spawned processes share only a throwaway SQLite database and sync gates."""
import multiprocessing
from pathlib import Path
import threading

from _schema_guard_utils import _use_temp_database


def _owner_process(db_path, workflow_id, allow_poll, allow_completion, abort, messages):
    import database
    import engine as engine_module
    import engine_core.lifecycle as lifecycle
    from engine import RunSignalPolicy, WorkflowEngine
    from executors import ExecutorResult

    database.DATABASE_PATH = Path(db_path)
    database.init_db()
    lifecycle.LOG_DIR = Path(db_path).parent / "owner-logs"
    try:
        import database_run_ownership
    except ImportError:
        database_run_ownership = None
    if database_run_ownership is not None:
        real_poll = database_run_ownership.acknowledge_stop_requests

        def gated_poll(*args, **kwargs):
            if not threading.current_thread().name.startswith("run-owner-"):
                return real_poll(*args, **kwargs)
            if not allow_poll.wait(8):
                return []
            return real_poll(*args, **kwargs)
        database_run_ownership.acknowledge_stop_requests = gated_poll

    class ControlledExecutor:
        def execute(self, **kwargs):
            cancel_event = kwargs["cancel_event"]
            messages.put(("executor_entered", threading.get_ident()))
            while not cancel_event.wait(0.05):
                if abort.is_set():
                    return ExecutorResult(success=False, exit_code=1, error_message="test abort")
            messages.put(("executor_cancelled", True))
            allow_completion.wait(8)
            return ExecutorResult(success=False, exit_code=-1, error_message="用户取消", extra={"cancelled": True})

    engine_module.get_executor = lambda *_args: ControlledExecutor()
    engine = WorkflowEngine()
    engine._cleanup_old_logs_async = lambda *_args: None
    engine._emit_log = lambda *_args: None
    try:
        result = engine.run_all(workflow_id)
        messages.put(("owner_finished", result))
    finally:
        engine.shutdown(wait=True)
        database.cleanup_session()
        messages.put(("owner_threads", [t.name for t in threading.enumerate() if t.name.startswith("run-owner-")]))
        database._engine.dispose()


def _requester_process(db_path, history_id, messages):
    import database
    from engine import WorkflowEngine
    from models import RunHistory

    database.DATABASE_PATH = Path(db_path)
    database.init_db()
    engine = WorkflowEngine()
    engine._emit_log = lambda *_args: None
    try:
        result = engine.force_stop_run(history_id)
        with database.get_session() as session:
            status = session.get(RunHistory, history_id).status
        messages.put(("requested", getattr(result, "status", None), status))
    finally:
        engine.shutdown()
        database.cleanup_session()
        database._engine.dispose()


def test_nonowner_request_is_nonterminal_until_actual_owner_cancels(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKFLOW_APP_DATA_DIR", str(tmp_path / "process-app-data"))
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("multiprocess owner")
    db.create_step(workflow.id, "controlled", script_path="unused.py")
    context = multiprocessing.get_context("spawn")
    allow_poll = context.Event()
    allow_completion = context.Event()
    abort = context.Event()
    messages = context.Queue()
    owner = context.Process(target=_owner_process, args=(str(db.DATABASE_PATH), workflow.id, allow_poll, allow_completion, abort, messages))
    requester = None
    owner.start()
    try:
        assert messages.get(timeout=12)[0] == "executor_entered"
        history = db.get_run_histories_by_workflow(workflow.id)[0]
        requester = context.Process(target=_requester_process, args=(str(db.DATABASE_PATH), history.id, messages))
        requester.start()
        request = messages.get(timeout=12)
        requester.join(timeout=5)
        assert requester.exitcode == 0
        assert request[0] == "requested"
        assert request[2] == "running", "nonowner must not publish terminal state before owner reacts"
        assert request[1] == "requested"
        assert db.get_step_logs_by_run(history.id)[0].status == "running"
        allow_poll.set()
        assert messages.get(timeout=8) == ("executor_cancelled", True)
        from database_run_ownership import get_stop_state
        assert get_stop_state(history.id).status == "acknowledged"
        assert db.get_run_histories_by_workflow(workflow.id)[0].status == "running"
        assert db.get_step_logs_by_run(history.id)[0].status == "running"
        allow_completion.set()
        assert messages.get(timeout=8) == ("owner_finished", False)
        assert messages.get(timeout=8) == ("owner_threads", [])
        owner.join(timeout=8)
        assert owner.exitcode == 0
        assert db.get_run_histories_by_workflow(workflow.id)[0].status == "cancelled"
        assert db.get_step_logs_by_run(history.id)[0].status == "cancelled"
        from database_run_ownership import get_stop_state
        assert get_stop_state(history.id).status == "completed"
    finally:
        allow_poll.set()
        allow_completion.set()
        abort.set()
        if requester is not None:
            requester.join(timeout=12)
        owner.join(timeout=12)
        messages.close()
        messages.join_thread()
        db.cleanup_session()
        db._engine.dispose()
        assert not owner.is_alive()
        assert requester is None or not requester.is_alive()
