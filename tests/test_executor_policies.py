# -*- coding: utf-8 -*-
"""执行器策略与发现逻辑测试"""

import sys
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import WorkflowEngine, StepResult
from executors.base import ExecutorResult
from executors.powerbi_executor import PowerBIExecutor
from executors.python_executor import PythonExecutor, _get_python_executable
from executors.sub_workflow_executor import SubWorkflowExecutor


def test_python_executor_rejects_non_python_script(tmp_path: Path):
    script = tmp_path / "job.txt"
    script.write_text("echo nope", encoding="utf-8")

    result = PythonExecutor().execute(str(script), log_dir=tmp_path / "logs")

    assert result.success is False
    assert "不支持的脚本类型" in (result.error_message or "")


def test_python_executor_rejects_non_string_args(tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")

    result = PythonExecutor().execute(str(script), args=["--ok", 1], log_dir=tmp_path / "logs")

    assert result.success is False
    assert "参数必须全部为字符串" in (result.error_message or "")


def test_python_executor_rejects_missing_work_dir(tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")

    result = PythonExecutor().execute(str(script), cwd="missing", log_dir=tmp_path / "logs")

    assert result.success is False
    assert "工作目录不存在" in (result.error_message or "")


def test_get_python_executable_prefers_python3_before_hardcoded(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("executors.python_executor.shutil.which", lambda name: {"python": None, "python3": "C:/Tools/python3.exe", "py": None}.get(name))

    result = _get_python_executable()

    assert result == "C:/Tools/python3.exe"


def test_powerbi_executor_prefers_path_lookup_before_fallbacks(monkeypatch):
    monkeypatch.setattr("executors.powerbi_executor.shutil.which", lambda name: "C:/Tools/PBIDesktop.exe" if name in {"PBIDesktop.exe", "PBIDesktop"} else None)
    monkeypatch.setattr("executors.powerbi_executor.os.path.exists", lambda path: False)

    result = PowerBIExecutor().find_pbidesktop()

    assert result == "C:/Tools/PBIDesktop.exe"


def test_sub_workflow_executor_uses_injected_runner(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    calls = []

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        workflow_runner=lambda workflow_id, reason="manual": calls.append((workflow_id, reason)) or True,
    )

    assert result.success is True
    assert calls == [(5, "sub_workflow")]


def test_engine_run_sub_workflow_reuses_parent_context_without_lock_conflict(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(
            id=5,
            uid="wf-child",
            name="子工作流",
            log_retention_days=1,
            single_script_enabled=False,
            parallel_enabled=False,
            get_notify_config=lambda: {},
        )
        calls = {}

        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 5 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: [SimpleNamespace(id=1)] if workflow_id == 5 else [])

        def fake_create_run_history(**kwargs):
            calls["create_run_history"] = kwargs
            return SimpleNamespace(
                id=101,
                run_id="child-run",
                trace_id=kwargs.get("trace_id") or "child-trace",
                parent_run_id=kwargs.get("parent_run_id"),
            )

        def fake_execute_steps(current_workflow, steps, run_history_id, log_dir, signal_policy, run_cancel_event=None):
            calls["execute_steps"] = {
                "workflow": current_workflow,
                "steps": steps,
                "run_history_id": run_history_id,
                "signal_policy": signal_policy,
                "run_cancel_event": run_cancel_event,
            }
            return True

        monkeypatch.setattr("engine.create_run_history", fake_create_run_history)
        monkeypatch.setattr("engine.update_run_history", lambda *args, **kwargs: None)
        # CA2: 生命周期 DB 调用现在通过 engine_core.lifecycle，monkeypatch 需要补 patch
        monkeypatch.setattr("engine_core.lifecycle.create_run_history", fake_create_run_history)
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        engine._running = True
        engine._current_run_id = "parent-run"
        engine._current_trace_id = "trace-root"

        result = engine.run_sub_workflow(5)

        assert result is True
        assert calls["create_run_history"]["parent_run_id"] == "parent-run"
        assert calls["create_run_history"]["trace_id"] == "trace-root"
        assert calls["execute_steps"]["run_history_id"] == 101
        assert calls["execute_steps"]["signal_policy"].emit_run_signals is False
        assert calls["execute_steps"]["signal_policy"].emit_step_signals is False
        assert calls["execute_steps"]["run_cancel_event"] is None
        assert engine._running is True
        assert engine._current_run_id == "parent-run"
        assert engine._current_trace_id == "trace-root"
    finally:
        engine.shutdown(wait=False)


def test_engine_run_sub_workflow_forwards_nested_cancel_event(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    cancel_event = threading.Event()
    try:
        workflow = SimpleNamespace(
            id=5,
            uid="wf-child",
            name="子工作流",
            log_retention_days=1,
            single_script_enabled=False,
            parallel_enabled=False,
            get_notify_config=lambda: {},
        )
        calls = {}

        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 5 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: [SimpleNamespace(id=1)] if workflow_id == 5 else [])

        def fake_create_run_history(**kwargs):
            return SimpleNamespace(
                id=101,
                run_id="child-run",
                trace_id=kwargs.get("trace_id") or "child-trace",
                parent_run_id=kwargs.get("parent_run_id"),
            )

        def fake_execute_steps(current_workflow, steps, run_history_id, log_dir, signal_policy, run_cancel_event=None):
            calls["run_cancel_event"] = run_cancel_event
            return False

        monkeypatch.setattr("engine.create_run_history", fake_create_run_history)
        monkeypatch.setattr("engine.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine_core.lifecycle.create_run_history", fake_create_run_history)
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        result = engine.run_sub_workflow(5, cancel_event=cancel_event)

        assert result is False
        assert calls["run_cancel_event"] is cancel_event
    finally:
        engine.shutdown(wait=False)


def test_sub_workflow_executor_returns_promptly_when_cancelled_during_wait(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    outer_cancel = threading.Event()
    nested_cancel_events = []

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    def workflow_runner(workflow_id, reason="manual", cancel_event=None):
        nested_cancel_events.append(cancel_event)
        if cancel_event is not None:
            cancel_event.wait(1.0)
        else:
            time.sleep(0.8)
        return False

    threading.Thread(target=lambda: (time.sleep(0.05), outer_cancel.set()), daemon=True).start()

    started_at = time.perf_counter()
    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        timeout=5,
        cancel_event=outer_cancel,
        workflow_runner=workflow_runner,
    )
    elapsed = time.perf_counter() - started_at

    assert result.success is False
    assert result.error_message == "用户取消"
    assert elapsed < 0.3
    assert nested_cancel_events
    assert nested_cancel_events[0] is not None
    assert nested_cancel_events[0].is_set() is True


def test_sub_workflow_executor_timeout_signals_nested_cancel(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    nested_cancel_events = []

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    def workflow_runner(workflow_id, reason="manual", cancel_event=None):
        nested_cancel_events.append(cancel_event)
        if cancel_event is not None:
            cancel_event.wait(1.0)
        else:
            time.sleep(0.5)
        return False

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        timeout=0.05,
        workflow_runner=workflow_runner,
    )

    assert result.success is False
    assert "超时" in (result.error_message or "")
    assert nested_cancel_events
    assert nested_cancel_events[0] is not None
    assert nested_cancel_events[0].is_set() is True


def test_powerbi_executor_can_cancel_during_startup_wait(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")
    cancel_event = threading.Event()
    cancel_event.set()

    class DummyProc:
        def __init__(self):
            self.returncode = 0
            self.terminated = False
            self.pid = 12345

        def poll(self):
            return None if not self.terminated else self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -1

        def kill(self):
            self.terminated = True
            self.returncode = -1

        def wait(self, timeout=None):
            self.terminated = True
            self.returncode = -1
            return self.returncode

        def communicate(self, timeout=None):
            return b"", b""

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)

    result = PowerBIExecutor().execute(
        str(pbix),
        log_dir=tmp_path / "logs",
        timeout=5,
        cancel_event=cancel_event,
    )

    assert result.success is False
    assert result.exit_code == -1
    assert result.error_message == "用户取消"
    assert proc.terminated is True


def test_engine_maps_executor_cancellation_to_cancelled_step(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=2,
            uid="step-powerbi",
            order=1,
            name="Power BI",
            step_type="powerbi_refresh",
            script_path="demo.pbix",
            cwd="",
            chart_theme="",
            timeout_seconds=30,
            retry_count=0,
            get_args=lambda: [],
            workflow_id=1,
        )
        step_log = SimpleNamespace(id=301)
        captured = {}

        class CancelledExecutor:
            def execute(self, **kwargs):
                kwargs["cancel_event"].set()
                engine._cancelled = True
                return ExecutorResult(
                    success=False,
                    exit_code=-1,
                    start_time=None,
                    end_time=None,
                    error_message="用户取消",
                )

        def fake_finish_step(current_step, step_log_id, result, exec_result=None, signal_policy=None):
            captured["result"] = result

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine.get_executor", lambda step_type: CancelledExecutor())
        monkeypatch.setattr(engine, "_finish_step", fake_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)
        engine._cancelled = False

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert result.status == "cancelled"
        assert result.exit_code == -1
        assert captured["result"].status == "cancelled"
    finally:
        engine.shutdown(wait=False)


def test_execute_parallel_steps_cleans_up_worker_sessions(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(max_workers=2)
        steps = [
            SimpleNamespace(id=1, order=1, name="A"),
            SimpleNamespace(id=2, order=2, name="B"),
        ]
        cleanup_calls = []

        monkeypatch.setattr(
            "engine.cleanup_session",
            lambda: cleanup_calls.append(threading.get_ident()),
        )
        monkeypatch.setattr(
            engine,
            "_execute_single_step",
            lambda workflow, step, run_history_id, log_dir, signal_policy, prev_step_status_map=None, run_cancel_event=None: StepResult(
                step_id=step.id,
                step_name=step.name,
                status="success",
                exit_code=0,
            ),
        )

        results = engine._execute_parallel_steps(
            workflow,
            steps,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(),
        )

        assert [result.step_id for result in results] == [1, 2]
        assert len(cleanup_calls) == 2
    finally:
        engine.shutdown(wait=False)


def test_finish_step_logs_duration_and_emits_it(monkeypatch):
    engine = WorkflowEngine()
    try:
        step = SimpleNamespace(id=7, name="步骤A", order=0)
        result = StepResult(
            step_id=7,
            step_name="步骤A",
            status="success",
            exit_code=0,
            start_time=datetime(2026, 1, 1, 10, 0, 0),
            end_time=datetime(2026, 1, 1, 10, 1, 23),
        )
        logs = []
        emitted = []

        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: logs.append(message))
        engine.step_finished.connect(lambda step_id, step_name, status, duration: emitted.append((step_id, step_name, status, duration)))

        engine._finish_step(
            step=step,
            step_log_id=99,
            result=result,
            signal_policy=SimpleNamespace(emit_step_signals=True),
        )

        assert logs == ["步骤 [0] 步骤A 成功 · 耗时 1m23s"]
        assert emitted == [(7, "步骤A", "success", 83.0)]
    finally:
        engine.shutdown(wait=False)
