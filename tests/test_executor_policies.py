# -*- coding: utf-8 -*-
"""执行器策略与发现逻辑测试"""

import io
import os
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
from executors.result_policy import (
    ResultPolicyKeys,
    build_policy_extra,
    has_non_retryable_policy,
)
from executors.sub_workflow_executor import SubWorkflowExecutor


def test_python_executor_rejects_non_python_script(tmp_path: Path):
    script = tmp_path / "job.txt"
    script.write_text("echo nope", encoding="utf-8")

    result = PythonExecutor().execute(str(script), log_dir=tmp_path / "logs")

    assert result.success is False
    assert "不支持的脚本类型" in (result.error_message or "")


def test_result_policy_helpers_centralize_retry_flags():
    extra = build_policy_extra(
        manual_required=True,
        background_risk=True,
        extra_fields={"custom_reason": "manual-check"},
    )

    assert extra[ResultPolicyKeys.MANUAL_REQUIRED] is True
    assert extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    assert ResultPolicyKeys.NOTE not in extra
    assert extra["custom_reason"] == "manual-check"
    assert has_non_retryable_policy(extra) is True
    assert has_non_retryable_policy(build_policy_extra(manual_required=False)) is False


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

        def communicate(self, timeout=None):
            return b"", b""

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

        def communicate(self, timeout=None):
            return b"", b""

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


def test_excel_executor_can_cancel_while_async_wait_method_is_blocked(monkeypatch, tmp_path: Path):
    workbook_path = tmp_path / "blocked.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    cancel_event = threading.Event()
    release_wait = threading.Event()
    app = SimpleNamespace(
        Workbooks=None,
        Visible=False,
        DisplayAlerts=False,
        Hwnd=1234,
        CalculationState=1,
        Refreshing=True,
    )

    class FakeWorkbook:
        Refreshing = True
        Connections = []

        def RefreshAll(self):
            return None

        def Save(self):
            raise AssertionError("cancelled execution should not save workbook")

        def Close(self, SaveChanges=True):
            return None

    class FakeWorkbooks:
        def Open(self, path):
            return FakeWorkbook()

    def calculate_until_async_queries_done():
        release_wait.wait(5)

    def quit_excel():
        return None

    app.Workbooks = FakeWorkbooks()
    app.CalculateUntilAsyncQueriesDone = calculate_until_async_queries_done
    app.Quit = quit_excel

    install_fake_excel_modules(monkeypatch, dispatch_ex=lambda _name: app)
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (0, 4321)),
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    threading.Thread(target=lambda: (time.sleep(0.05), cancel_event.set()), daemon=True).start()

    started_at = time.perf_counter()
    result = ExcelExecutor().execute(
        str(workbook_path),
        log_dir=tmp_path / "logs",
        timeout=2,
        cancel_event=cancel_event,
    )
    elapsed = time.perf_counter() - started_at
    release_wait.set()

    assert result.success is False
    assert "用户取消" in (result.error_message or "")
    assert elapsed < 1.0


def test_excel_executor_times_out_while_async_wait_method_is_blocked(monkeypatch, tmp_path: Path):
    workbook_path = tmp_path / "timeout.xlsx"
    workbook_path.write_text("", encoding="utf-8")
    release_wait = threading.Event()
    app = SimpleNamespace(
        Workbooks=None,
        Visible=False,
        DisplayAlerts=False,
        Hwnd=1234,
        CalculationState=1,
        Refreshing=True,
    )

    class FakeWorkbook:
        Refreshing = True
        Connections = []

        def RefreshAll(self):
            return None

        def Save(self):
            raise AssertionError("timed out execution should not save workbook")

        def Close(self, SaveChanges=True):
            return None

    class FakeWorkbooks:
        def Open(self, path):
            return FakeWorkbook()

    def calculate_until_async_queries_done():
        release_wait.wait(5)

    app.Workbooks = FakeWorkbooks()
    app.CalculateUntilAsyncQueriesDone = calculate_until_async_queries_done
    app.Quit = lambda: None

    install_fake_excel_modules(monkeypatch, dispatch_ex=lambda _name: app)
    monkeypatch.setitem(
        sys.modules,
        "win32process",
        SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (0, 4321)),
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    started_at = time.perf_counter()
    result = ExcelExecutor().execute(
        str(workbook_path),
        log_dir=tmp_path / "logs",
        timeout=0.1,
    )
    elapsed = time.perf_counter() - started_at
    release_wait.set()

    assert result.success is False
    assert "刷新超时" in (result.error_message or "")
    assert elapsed < 1.5


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


def test_powerbi_auto_refresh_logs_when_pid_attach_falls_back_to_path(monkeypatch):
    calls = []

    class FakeWindow:
        def set_focus(self):
            calls.append(("focus",))

        def type_keys(self, keys):
            calls.append(("keys", keys))

    class FakeApplication:
        def __init__(self, backend=None):
            calls.append(("backend", backend))

        def connect(self, **kwargs):
            calls.append(("connect", kwargs))
            if "process" in kwargs:
                raise RuntimeError("pid attach failed")
            return self

        def top_window(self):
            return FakeWindow()

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Application=FakeApplication))
    logs = []
    errors = []

    result = PowerBIExecutor()._try_auto_refresh("C:/Tools/PBIDesktop.exe", logs, errors, pid=4321)

    assert result is True
    assert errors == []
    assert any("回退按路径连接" in message and "pid=4321" in message for message in logs)
    assert ("connect", {"process": 4321, "timeout": 10}) in calls
    assert ("connect", {"path": "C:/Tools/PBIDesktop.exe", "timeout": 10}) in calls
    assert ("keys", "{F5}") in calls


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
        workflow_runner=lambda workflow_id, reason="manual", cancel_event=None: calls.append(
            (workflow_id, reason, cancel_event is not None)
        ) or True,
    )

    assert result.success is True
    assert calls == [(5, "sub_workflow", True)]


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

        monkeypatch.setattr("engine.update_run_history", lambda *args, **kwargs: None)
        # CA2: 生命周期 DB 调用现在通过 engine_core.lifecycle。
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


def test_powerbi_executor_fails_when_auto_refresh_cannot_be_triggered(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")
    killed = {}

    class DummyProc:
        pid = 2222
        returncode = None

        def poll(self):
            return None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(PowerBIExecutor, "_try_auto_refresh", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "executors.powerbi_executor._kill_process_tree",
        lambda current_proc: killed.setdefault("pid", current_proc.pid),
    )

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=5)

    assert result.success is False
    assert result.exit_code == 1
    assert result.extra["manual_required"] is False
    assert "自动刷新" in (result.error_message or "")
    assert killed["pid"] == 2222


def test_powerbi_executor_no_auto_refresh_requires_manual_confirmation(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")

    class DummyProc:
        pid = 3333
        returncode = None

        def poll(self):
            return None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.wait_with_cancel",
        lambda proc, timeout, cancel_event=None, check_interval=1.0: (True, False),
    )

    result = PowerBIExecutor().execute(
        str(pbix),
        args=["--no-auto-refresh"],
        log_dir=tmp_path / "logs",
        timeout=35,
    )

    assert result.success is False
    assert result.exit_code == 2
    assert result.extra["manual_required"] is True
    assert "人工刷新确认" in (result.error_message or "")


def test_powerbi_executor_timeout_not_treated_as_infinite_wait(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")
    killed = {}

    class DummyProc:
        pid = 3434
        returncode = None

        def poll(self):
            return None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(PowerBIExecutor, "_try_auto_refresh", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.wait_with_cancel",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("timeout=0 must not wait forever")),
    )
    monkeypatch.setattr(
        "executors.powerbi_executor._kill_process_tree",
        lambda current_proc: killed.setdefault("pid", current_proc.pid),
    )

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=5)

    assert result.success is False
    assert result.exit_code == -1
    assert result.error_message == "等待超时 (5秒)"
    assert killed["pid"] == 3434


def test_powerbi_executor_no_auto_close_never_reports_plain_success(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")

    class DummyProc:
        pid = 4444
        returncode = None

        def poll(self):
            return None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(PowerBIExecutor, "_try_auto_refresh", lambda *args, **kwargs: True)

    result = PowerBIExecutor().execute(
        str(pbix),
        args=["--no-auto-close"],
        log_dir=tmp_path / "logs",
        timeout=5,
    )

    assert result.success is False
    assert result.exit_code == 2
    assert result.extra["manual_required"] is True
    assert result.extra["background_risk"] is True
    assert "无法确认刷新完成" in (result.error_message or "")


def test_powerbi_executor_auto_close_without_completion_proof_returns_manual_required(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")

    class DummyProc:
        def __init__(self):
            self.pid = 4545
            self.returncode = None
            self.closed = False

        def poll(self):
            return self.returncode if self.closed else None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(PowerBIExecutor, "_try_auto_refresh", lambda *args, **kwargs: True)

    def fake_wait_with_cancel(current_proc, timeout, cancel_event=None, check_interval=1.0):
        current_proc.closed = True
        current_proc.returncode = 0
        return (True, False)

    monkeypatch.setattr("executors.powerbi_executor.BaseExecutor.wait_with_cancel", fake_wait_with_cancel)

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=35)

    assert result.success is False
    assert result.exit_code == 2
    assert result.extra["manual_required"] is True
    assert result.extra["proof_reason"] == "pbix_mtime_unchanged"
    assert "缺少刷新成功证明" in (result.error_message or "")
    assert "pbix_mtime_unchanged" in Path(result.stdout_path).read_text(encoding="utf-8")


def test_powerbi_executor_auto_close_returns_success_when_pbix_mtime_changes(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")
    original_mtime_ns = pbix.stat().st_mtime_ns

    class DummyProc:
        def __init__(self):
            self.pid = 4595
            self.returncode = None
            self.closed = False

        def poll(self):
            return self.returncode if self.closed else None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(PowerBIExecutor, "_try_auto_refresh", lambda *args, **kwargs: True)

    def fake_wait_with_cancel(current_proc, timeout, cancel_event=None, check_interval=1.0):
        current_proc.closed = True
        current_proc.returncode = 0
        updated_mtime_ns = original_mtime_ns + 1_000_000_000
        os.utime(pbix, ns=(updated_mtime_ns, updated_mtime_ns))
        return (True, False)

    monkeypatch.setattr("executors.powerbi_executor.BaseExecutor.wait_with_cancel", fake_wait_with_cancel)

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=35)

    assert result.success is True
    assert result.exit_code == 0
    assert result.extra["proof_type"] == "pbix_mtime_changed"
    assert "pbix_mtime_changed" in Path(result.stdout_path).read_text(encoding="utf-8")


def test_powerbi_executor_auto_close_detects_nonzero_exit_after_wait(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")

    class DummyProc:
        pid = 4646
        returncode = None

        def poll(self):
            return 7 if self.returncode == 7 else None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(PowerBIExecutor, "_try_auto_refresh", lambda *args, **kwargs: True)

    def fake_wait_with_cancel(current_proc, timeout, cancel_event=None, check_interval=1.0):
        current_proc.returncode = 7
        current_proc.closed = True
        return (True, False)

    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.wait_with_cancel",
        fake_wait_with_cancel,
    )

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=35)

    assert result.success is False
    assert result.exit_code == 7
    assert "退出码: 7" in (result.error_message or "")


def test_powerbi_executor_no_auto_refresh_and_no_auto_close_flags_background_risk(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")

    class DummyProc:
        pid = 5555
        returncode = None

        def poll(self):
            return None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )

    result = PowerBIExecutor().execute(
        str(pbix),
        args=["--no-auto-refresh", "--no-auto-close"],
        log_dir=tmp_path / "logs",
        timeout=5,
    )

    assert result.success is False
    assert result.exit_code == 2
    assert result.extra["manual_required"] is True
    assert result.extra["background_risk"] is True
    assert "无法确认刷新完成" in (result.error_message or "")


def test_powerbi_executor_cleans_up_process_tree_on_unexpected_exception_after_popen(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")
    killed = {}

    class DummyProc:
        pid = 6666
        returncode = None

        def poll(self):
            return None

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(
        PowerBIExecutor,
        "_try_auto_refresh",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom after popen")),
    )
    monkeypatch.setattr(
        "executors.powerbi_executor._kill_process_tree",
        lambda current_proc: killed.setdefault("pid", current_proc.pid),
    )

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=5)

    assert result.success is False
    assert "boom after popen" in (result.error_message or "")
    assert killed["pid"] == 6666


def test_powerbi_executor_unexpected_exception_skips_cleanup_for_exited_process(monkeypatch, tmp_path: Path):
    pbix = tmp_path / "demo.pbix"
    pbix.write_text("demo", encoding="utf-8")
    killed = {"count": 0}

    class DummyProc:
        pid = 7777
        returncode = 0

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return b"", b""

    proc = DummyProc()

    monkeypatch.setattr(PowerBIExecutor, "find_pbidesktop", lambda self: "C:/Tools/PBIDesktop.exe")
    monkeypatch.setattr("executors.powerbi_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(
        "executors.powerbi_executor.BaseExecutor.sleep_with_cancel",
        lambda duration, cancel_event=None, chunk=1.0: False,
    )
    monkeypatch.setattr(
        PowerBIExecutor,
        "_try_auto_refresh",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom after exit")),
    )
    monkeypatch.setattr(
        "executors.powerbi_executor._kill_process_tree",
        lambda current_proc: killed.__setitem__("count", killed["count"] + 1),
    )

    result = PowerBIExecutor().execute(str(pbix), log_dir=tmp_path / "logs", timeout=5)

    assert result.success is False
    assert "boom after exit" in (result.error_message or "")
    assert killed["count"] == 0


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


def test_execute_single_step_marks_log_failed_when_execution_chain_crashes(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=2,
            uid="step-crash",
            order=1,
            name="Crash",
            step_type="python",
        )
        step_log = SimpleNamespace(id=501)
        updates = []

        def fake_update_step_log(step_log_id, **kwargs):
            updates.append((step_log_id, kwargs))

        def fail_finish_step(*args, **kwargs):
            raise RuntimeError("finish failed")

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", fake_update_step_log)
        monkeypatch.setattr("engine.get_executor", lambda step_type: object())
        monkeypatch.setattr(
            engine,
            "_execute_step_with_retries",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("executor chain crashed")),
        )
        monkeypatch.setattr(engine, "_finish_step", fail_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert result.status == "failure"
        assert result.exit_code == 1
        assert "executor chain crashed" in result.error_message
        assert updates[0] == (501, {"status": "running", "start_time": updates[0][1]["start_time"]})
        assert updates[-1][0] == 501
        assert updates[-1][1]["status"] == "failure"
        assert updates[-1][1]["exit_code"] == 1
        assert "executor chain crashed" in updates[-1][1]["error_message"]
        assert "finish failed" in updates[-1][1]["error_message"]
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_marks_log_failed_when_running_mark_crashes(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=3,
            uid="step-start-crash",
            order=1,
            name="Start Crash",
            step_type="python",
        )
        step_log = SimpleNamespace(id=502)
        updates = []

        def fake_update_step_log(step_log_id, **kwargs):
            if kwargs.get("status") == "running":
                raise RuntimeError("running mark failed")
            updates.append((step_log_id, kwargs))

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", fake_update_step_log)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert result.status == "failure"
        assert result.exit_code == 1
        assert "running mark failed" in result.error_message
        assert updates[-1][0] == 502
        assert updates[-1][1]["status"] == "failure"
        assert "running mark failed" in updates[-1][1]["error_message"]
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_does_not_retry_manual_required_background_risk(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=4,
            uid="step-powerbi-manual",
            order=1,
            name="Power BI Manual",
            step_type="powerbi_refresh",
            script_path="demo.pbix",
            cwd="",
            chart_theme="",
            timeout_seconds=30,
            retry_count=2,
            get_args=lambda: ["--no-auto-close"],
        )
        step_log = SimpleNamespace(id=503)
        attempts = []
        finished = []

        class ManualRiskExecutor:
            def execute(self, **kwargs):
                attempts.append(kwargs)
                return ExecutorResult(
                    success=False,
                    exit_code=2,
                    error_message="Power BI 未自动关闭，当前步骤无法确认刷新完成",
                    extra=build_policy_extra(
                        manual_required=True,
                        background_risk=True,
                    ),
                )

        def fake_finish_step(current_step, step_log_id, result, exec_result=None, signal_policy=None):
            finished.append((current_step, step_log_id, result, exec_result))

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine.get_executor", lambda step_type: ManualRiskExecutor())
        monkeypatch.setattr(engine, "_finish_step", fake_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert len(attempts) == 1
        assert result.status == "failure"
        assert result.exit_code == 2
        assert "未自动关闭" in result.error_message
        assert finished[-1][2].status == "failure"
        assert finished[-1][3].extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_does_not_retry_manual_required_without_background_risk(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=5,
            uid="step-powerbi-no-auto-refresh",
            order=1,
            name="Power BI Manual Refresh",
            step_type="powerbi_refresh",
            script_path="demo.pbix",
            cwd="",
            chart_theme="",
            timeout_seconds=30,
            retry_count=2,
            get_args=lambda: ["--no-auto-refresh"],
        )
        step_log = SimpleNamespace(id=504)
        attempts = []
        finished = []

        class ManualRequiredExecutor:
            def execute(self, **kwargs):
                attempts.append(kwargs)
                return ExecutorResult(
                    success=False,
                    exit_code=2,
                    error_message="Power BI 需要人工刷新确认，当前步骤未自动确认成功",
                    extra=build_policy_extra(manual_required=True),
                )

        def fake_finish_step(current_step, step_log_id, result, exec_result=None, signal_policy=None):
            finished.append((current_step, step_log_id, result, exec_result))

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine.get_executor", lambda step_type: ManualRequiredExecutor())
        monkeypatch.setattr(engine, "_finish_step", fake_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert len(attempts) == 1
        assert result.status == "failure"
        assert result.exit_code == 2
        assert "人工刷新确认" in result.error_message
        assert finished[-1][2].status == "failure"
        assert finished[-1][3].extra == build_policy_extra(manual_required=True)
    finally:
        engine.shutdown(wait=False)
