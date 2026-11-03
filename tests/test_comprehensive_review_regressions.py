# -*- coding: utf-8 -*-
"""2026-10 全面审查：CLI、执行器与导入边界的回归测试。"""

import io
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cli
from database_import_validation import validate_import_payload
from executors.bat_executor import BatExecutor
from executors.python_executor import PythonExecutor


def _patch_cli_test_engine(monkeypatch):
    _, _, run_mode, signal_policy = cli._import_engine()
    monkeypatch.setattr(cli, "_import_engine", lambda: (None, None, run_mode, signal_policy))
    monkeypatch.setattr(cli, "get_workflow_by_id", lambda _wid: SimpleNamespace(name="测试"))
    monkeypatch.setattr(cli, "get_run_histories_by_workflow", lambda *_a, **_k: [])




def test_cli_uses_finished_status_after_engine_resets_cancel(monkeypatch):
    _patch_cli_test_engine(monkeypatch)
    runner = cli.CLIEngine.__new__(cli.CLIEngine)
    engine = SimpleNamespace(
        is_cancelled=False, is_running=False,
        error_details=SimpleNamespace(connect=lambda _slot: None),
    )
    engine.run = lambda *_a, **_k: (
        runner._on_workflow_finished(1, "run-current", "cancelled"), False
    )[1]
    runner.engine = engine
    notifications = []
    monkeypatch.setattr(cli, "send_cli_notification", lambda **kwargs: notifications.append(kwargs))
    assert runner.run(1) is False
    assert notifications[0]["cancelled"] is True
    assert notifications[0]["last_run_id"] == "run-current"


def test_cli_metadata_does_not_borrow_unrelated_history(monkeypatch):
    runner = cli.CLIEngine.__new__(cli.CLIEngine)
    runner._last_run_id = None
    monkeypatch.setattr(
        cli, "get_run_histories_by_workflow",
        lambda *_a, **_k: pytest.fail("无本次 Run ID 时不应查询历史"),
    )
    runner._refresh_last_run_metadata(1)

    runner._last_run_id = "current"
    monkeypatch.setattr(
        cli, "get_run_histories_by_workflow",
        lambda *_a, **_k: [SimpleNamespace(run_id="older")],
    )
    runner._refresh_last_run_metadata(1)
    assert runner._last_run_id == "current"


def test_cli_close_shuts_down_auxiliary_pool():
    calls = []
    runner = cli.CLIEngine.__new__(cli.CLIEngine)
    runner.engine = SimpleNamespace(shutdown=lambda wait: calls.append(wait))
    runner.close()
    assert calls == [True]


@pytest.mark.parametrize("executor_type", [PythonExecutor, BatExecutor])
def test_executor_cleanup_never_waits_without_timeout(executor_type):
    reached = []
    errors = []

    class DummyProc:
        def poll(self):
            return -1

        def communicate(self, timeout=None):
            pytest.fail("cleanup must not compete with the existing pipe readers")

        def wait(self, timeout=None):
            reached.append(timeout)
            assert timeout == executor_type.PROCESS_WAIT_TIMEOUT_SECONDS
            raise subprocess.TimeoutExpired("job", timeout)

    capture = SimpleNamespace(cleanup_failed=errors.append)
    executor_type()._cleanup_process_resources(DummyProc(), capture)
    assert reached == [executor_type.PROCESS_WAIT_TIMEOUT_SECONDS]
    assert len(errors) == 1
    assert "未确认进程退出" in errors[0]


@pytest.mark.parametrize(
    ("field", "value"),
    [("retry_count", -1), ("timeout_seconds", -1)],
)
def test_import_rejects_negative_execution_limits(field, value):
    payload = {
        "version": 1,
        "workflows": [{"name": "wf", "steps": [{"name": "s", field: value}]}],
    }
    with pytest.raises(ValueError, match=rf"{field}.*非负整数"):
        validate_import_payload(payload)


@pytest.mark.parametrize("field", ["retry_count", "timeout_seconds"])
def test_import_preserves_zero_and_default_execution_limits(field):
    for value in (None, 0):
        if field == "retry_count" and value is None:
            continue
        payload = {
            "version": 1,
            "workflows": [{"name": "wf", "steps": [{"name": "s", field: value}]}],
        }
        assert validate_import_payload(payload) is payload


def test_cli_rejects_overlapping_run_modes():
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["run", "wf", "--only", "a", "--from", "b"])
    assert exc_info.value.code == 2


def test_update_step_rejects_negative_execution_limits():
    from database_workflows import update_step

    for field in ("retry_count", "timeout_seconds"):
        with pytest.raises(ValueError, match=field):
            update_step(1, **{field: -1})


def test_legacy_global_digest_authorizes_safe_subset():
    from risk_path_review import build_run_plan, compute_digest, evaluate_run_plan

    risky = SimpleNamespace(id=1, uid="risky", script_path="C:/risky.py", cwd=None)
    safe = SimpleNamespace(id=2, uid="safe", script_path="scripts/safe.py", cwd=None)
    workflow = SimpleNamespace(
        id=1, risky_paths_review_required=False, risky_paths_revision=2,
        risky_paths_confirmed_digest=compute_digest(2, build_run_plan(
            SimpleNamespace(id=1), [risky],
        ).risk_records),
    )
    assert evaluate_run_plan(build_run_plan(workflow, [risky, safe], selected_steps=[safe])) is None


@pytest.fixture
def startup_run(monkeypatch, tmp_path):
    import engine_core.lifecycle as lifecycle
    from _schema_guard_utils import _use_temp_database
    from engine import WorkflowEngine

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("启动停止所有权")
    step = db.create_step(workflow.id, "A", script_path="scripts/a.py")
    engine = WorkflowEngine()
    observed = {"executed": []}
    monkeypatch.setattr(lifecycle, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(engine, "_cleanup_old_logs_async", lambda _workflow: None)
    monkeypatch.setattr(engine, "_emit_log", lambda _message: None)

    def execute_steps(_workflow, _steps, run_history_id, *_args, **_kwargs):
        observed["executed"].append(run_history_id)
        return True

    monkeypatch.setattr(engine, "_execute_steps", execute_steps)
    try:
        yield SimpleNamespace(db=db, workflow=workflow, step=step, engine=engine, observed=observed)
    finally:
        engine.shutdown(wait=False)


@pytest.mark.parametrize("stop_point", ("mkdir", "running_update", "after_begin"))
def test_force_stop_during_begin_run_propagates_cancellation(monkeypatch, startup_run, stop_point):
    import engine as engine_module
    import engine_core.lifecycle as lifecycle
    from engine import RunMode

    db, workflow, engine, observed = (
        startup_run.db, startup_run.workflow, startup_run.engine, startup_run.observed,
    )

    def stop_created_run():
        history = db.get_run_histories_by_workflow(workflow.id)[0]
        observed["stopped_id"] = history.id
        observed["active_at_stop"] = set(engine._active_run_ids)
        engine.force_stop_run(history.id)
        observed["cancelled_at_stop"] = engine.is_cancelled
        observed["status_at_stop"] = db.get_run_histories_by_workflow(workflow.id)[0].status

    if stop_point == "mkdir":
        real_mkdir = Path.mkdir

        def mkdir_then_stop(path, *args, **kwargs):
            stop_created_run()
            return real_mkdir(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mkdir_then_stop)
    elif stop_point == "running_update":
        real_update = lifecycle.update_run_history

        def update_then_stop(run_history_id, **kwargs):
            if kwargs.get("status") == "running":
                stop_created_run()
            return real_update(run_history_id, **kwargs)

        monkeypatch.setattr(lifecycle, "update_run_history", update_then_stop)
    else:
        original_begin = engine_module._begin_run

        def begin_then_force_stop(**kwargs):
            ctx = original_begin(**kwargs)
            stop_created_run()
            observed["begin_returned"] = ctx.run_history_id
            return ctx

        monkeypatch.setattr(engine_module, "_begin_run", begin_then_force_stop)

    assert engine.run(workflow.id, RunMode.FULL) is False
    history = db.get_run_histories_by_workflow(workflow.id)[0]
    # 断言留在 engine 捕获异常的边界之外，避免未到 force_stop 分支也假绿。
    assert observed.get("stopped_id") == history.id
    assert observed["active_at_stop"] == {history.id}
    assert observed["cancelled_at_stop"] is True
    assert observed["status_at_stop"] != "cancelled", "活动运行应交给引擎 finally 收尾"
    if stop_point == "after_begin":
        assert observed.get("begin_returned") == history.id
    assert observed["executed"] == []
    assert history.status == "cancelled"
    assert history.end_time is not None
    assert engine._active_run_ids == set()
    assert engine.current_run_history_id is None
    assert engine.is_running is False


def test_force_stop_different_orphan_during_initialization_leaves_current_run_alive(
    monkeypatch, startup_run,
):
    import engine_core.lifecycle as lifecycle
    from engine import RunMode

    db, workflow, engine, observed = (
        startup_run.db, startup_run.workflow, startup_run.engine, startup_run.observed,
    )
    orphan = db.create_run_history(workflow.id)
    db.update_run_history(orphan.id, status="running")
    orphan_step = db.create_step_log(orphan.id, startup_run.step.id, order=1)
    db.update_step_log(orphan_step.id, status="running")
    real_update = lifecycle.update_run_history

    def stop_orphan_before_running_update(run_history_id, **kwargs):
        if kwargs.get("status") == "running":
            observed["initializing_id"] = run_history_id
            observed["active_at_stop"] = set(engine._active_run_ids)
            engine.force_stop_run(orphan.id)
            observed["cancelled_at_stop"] = engine.is_cancelled
        return real_update(run_history_id, **kwargs)

    monkeypatch.setattr(lifecycle, "update_run_history", stop_orphan_before_running_update)
    assert engine.run(workflow.id, RunMode.FULL) is True
    histories = {history.id: history for history in db.get_run_histories_by_workflow(workflow.id)}
    assert observed.get("initializing_id") in histories
    current_id = observed["initializing_id"]
    assert current_id != orphan.id
    assert observed["active_at_stop"] == {current_id}
    assert observed["cancelled_at_stop"] is False
    assert observed["executed"] == [current_id]
    assert histories[current_id].status == "success"
    assert histories[orphan.id].status == "cancelled"
    assert histories[orphan.id].end_time is not None
    assert db.get_step_logs_by_run(orphan.id)[0].status == "cancelled"
    assert engine._active_run_ids == set()
    assert engine.current_run_history_id is None


def test_force_stop_cannot_observe_created_id_before_ownership_registration(monkeypatch, startup_run):
    import engine_core.lifecycle as lifecycle
    from engine import RunMode

    db, workflow, engine, observed = (
        startup_run.db, startup_run.workflow, startup_run.engine, startup_run.observed,
    )
    real_create = lifecycle.create_run_history
    stop_requested = threading.Event()
    stop_finished = threading.Event()
    workers = []

    class StopProbeLock:
        """实际进入 force_stop_run 的锁边界后再放行创建线程，避免靠 sleep 猜调度。"""

        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if threading.current_thread() in workers:
                stop_requested.set()
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    engine._lock = StopProbeLock()

    def create_then_request_stop(**kwargs):
        history = real_create(**kwargs)
        observed["created_id"] = history.id

        def stop_created_run():
            try:
                engine.force_stop_run(history.id)
                observed["stop_returned"] = True
            finally:
                db.cleanup_session()
                stop_finished.set()

        worker = threading.Thread(target=stop_created_run, daemon=True)
        workers.append(worker)
        worker.start()
        observed["stop_requested"] = stop_requested.wait(5)
        observed["creation_owns_lock"] = engine._lock.lock.locked()
        # 旧实现没有持锁；等待 stop 完成，使 commit→返回这个竞态可确定地复现。
        if not observed["creation_owns_lock"]:
            observed["stop_finished_in_gap"] = stop_finished.wait(5)
        return history

    real_mkdir = Path.mkdir

    def wait_for_stop_before_mkdir(path, *args, **kwargs):
        observed["stop_finished_before_mkdir"] = stop_finished.wait(5)
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(lifecycle, "create_run_history", create_then_request_stop)
    monkeypatch.setattr(Path, "mkdir", wait_for_stop_before_mkdir)
    try:
        assert engine.run(workflow.id, RunMode.FULL) is False
        for worker in workers:
            worker.join(timeout=5)
        histories = db.get_run_histories_by_workflow(workflow.id)
        assert observed.get("created_id") == histories[0].id
        assert observed.get("stop_requested") is True
        assert observed.get("stop_returned") is True
        assert observed.get("creation_owns_lock") is True
        assert observed.get("stop_finished_before_mkdir") is True
        assert all(not worker.is_alive() for worker in workers)
        assert observed["executed"] == []
        assert histories[0].status == "cancelled"
        assert engine._active_run_ids == set()
    finally:
        engine.cancel()
        for worker in workers:
            worker.join(timeout=5)
