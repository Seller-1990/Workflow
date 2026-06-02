# -*- coding: utf-8 -*-
"""执行器策略与发现逻辑测试"""

import io
import sys
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path


def install_fake_excel_modules(monkeypatch, dispatch_ex):
    pythoncom_mod = SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    win32_client_mod = SimpleNamespace(DispatchEx=dispatch_ex)
    win32_mod = SimpleNamespace(client=win32_client_mod)

    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom_mod)
    monkeypatch.setitem(sys.modules, "win32com", win32_mod)
    monkeypatch.setitem(sys.modules, "win32com.client", win32_client_mod)


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import WorkflowEngine, StepResult
from executors.base import ExecutorResult
from executors.excel_executor import ExcelExecutor
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


def test_python_executor_uses_process_tree_kill_on_cancel(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    cancel_event = threading.Event()
    killed = {}

    class DummyProc:
        def __init__(self):
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.pid = 4242
            self.returncode = None
            self.kill_called = False

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return b"", b""

        def wait(self, timeout=None):
            self.returncode = -1
            return self.returncode

        def kill(self):
            self.kill_called = True
            self.returncode = -1

    monkeypatch.setattr("executors.python_executor.subprocess.Popen", lambda *args, **kwargs: DummyProc())
    monkeypatch.setattr(
        PythonExecutor,
        "wait_with_cancel",
        staticmethod(lambda proc, timeout, cancel_event=None, check_interval=0.5: (True, True)),
    )
    monkeypatch.setattr(
        PythonExecutor,
        "kill_process_tree",
        staticmethod(lambda proc, taskkill_timeout=10, wait_timeout=5: killed.setdefault("pid", proc.pid)),
    )

    result = PythonExecutor().execute(str(script), log_dir=tmp_path / "logs", cancel_event=cancel_event)

    assert result.success is False
    assert result.error_message == "用户取消"
    assert killed["pid"] == 4242


def test_python_executor_uses_process_tree_kill_on_timeout(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    cancel_event = threading.Event()
    killed = {}

    class DummyProc:
        def __init__(self):
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.pid = 4343
            self.returncode = None
            self.kill_called = False

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -1
            return self.returncode

        def kill(self):
            self.kill_called = True
            self.returncode = -1

    monkeypatch.setattr("executors.python_executor.subprocess.Popen", lambda *args, **kwargs: DummyProc())
    monkeypatch.setattr(
        PythonExecutor,
        "wait_with_cancel",
        staticmethod(lambda proc, timeout, cancel_event=None, check_interval=0.5: (False, False)),
    )
    monkeypatch.setattr(
        PythonExecutor,
        "kill_process_tree",
        staticmethod(lambda proc, taskkill_timeout=10, wait_timeout=5: killed.setdefault("pid", proc.pid)),
    )

    result = PythonExecutor().execute(
        str(script),
        log_dir=tmp_path / "logs",
        cancel_event=cancel_event,
        timeout=1,
    )

    assert result.success is False
    assert result.error_message == "执行超时 (1秒)"
    assert killed["pid"] == 4343


def test_python_executor_includes_stderr_excerpt_in_error_message(tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text(
        "import sys\nprint('ERROR: boom failure', file=sys.stderr)\nsys.exit(1)\n",
        encoding="utf-8",
    )

    result = PythonExecutor().execute(str(script), log_dir=tmp_path / "logs")

    assert result.success is False
    assert "退出码: 1" in (result.error_message or "")
    assert "ERROR: boom failure" in (result.error_message or "")


def test_excel_executor_waits_for_async_queries_before_saving(monkeypatch, tmp_path: Path):
    workbook_path = tmp_path / "report.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    app = SimpleNamespace(
        Workbooks=None,
        Visible=False,
        DisplayAlerts=False,
        Hwnd=1234,
        CalculationState=1,
        calculate_calls=0,
        refresh_called=False,
    )

    class FakeConnection:
        def __init__(self):
            self.OLEDBConnection = SimpleNamespace(BackgroundQuery=True)

    class FakeWorkbook:
        def __init__(self):
            self.Connections = [FakeConnection()]
            self.saved = False
            self.closed = False
            self.Sheets = SimpleNamespace(Count=3)

        def RefreshAll(self):
            app.refresh_called = True

        def Save(self):
            self.saved = True

        def Close(self, SaveChanges=True):
            self.closed = True

    class FakeWorkbooks:
        def Open(self, path):
            app.opened_path = path
            return FakeWorkbook()

    def calculate_until_async_queries_done():
        app.calculate_calls += 1
        app.CalculationState = 0

    app.Workbooks = FakeWorkbooks()
    app.CalculateUntilAsyncQueriesDone = calculate_until_async_queries_done

    install_fake_excel_modules(monkeypatch, dispatch_ex=lambda _name: app)
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (0, 4321)),
    )

    result = ExcelExecutor().execute(str(workbook_path), log_dir=tmp_path / "logs", timeout=2)

    assert result.success is True
    assert app.calculate_calls == 1
    assert app.refresh_called is True


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


def test_powerbi_kill_process_tree_limits_cleanup_to_current_tree(monkeypatch):
    class FakeUnrelatedProcess:
        def __init__(self, pid):
            self.pid = pid
            self.info = {"pid": pid, "name": "PBIDesktop.exe"}
            self.killed = False

        def kill(self):
            self.killed = True

    class FakeRootProcess:
        def __init__(self, pid):
            self.pid = pid

        def children(self, recursive=True):
            return []

    unrelated = FakeUnrelatedProcess(9001)
    base_calls = []

    fake_psutil = SimpleNamespace(
        Process=lambda pid: FakeRootProcess(pid) if pid == 1234 else unrelated,
        process_iter=lambda attrs=None: [unrelated],
        NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
        AccessDenied=type("AccessDenied", (Exception,), {}),
        ZombieProcess=type("ZombieProcess", (Exception,), {}),
    )

    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr("executors.powerbi_executor.BaseExecutor.kill_process_tree", lambda proc: base_calls.append(proc.pid))

    from executors.powerbi_executor import _kill_process_tree

    class DummyProc:
        pid = 1234

    _kill_process_tree(DummyProc())

    assert base_calls == [1234]
    assert unrelated.killed is False


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


def test_sub_workflow_executor_returns_result_when_runner_raises(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    def workflow_runner(*args, **kwargs):
        raise RuntimeError("boom")

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        workflow_runner=workflow_runner,
    )

    assert result.success is False
    assert result.exit_code == 1
    assert "子工作流执行异常" in (result.error_message or "")
    assert "boom" in (result.error_message or "")


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
