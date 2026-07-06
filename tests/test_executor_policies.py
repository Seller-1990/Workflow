# -*- coding: utf-8 -*-
"""执行器策略与发现逻辑测试：Python/Excel 执行器与结果策略契约。

拆分自原 test_executor_policies.py（1000 行硬门槛，纯位置迁移）：
- PowerBI 执行器策略 → test_executor_policies_powerbi.py
- 引擎步骤执行与子工作流策略 → test_executor_policies_engine.py
- 共享伪件 → _executor_policy_utils.py
"""

import io
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _executor_policy_utils import install_fake_excel_modules
from executors.excel_executor import ExcelExecutor
from executors.python_executor import PythonExecutor, _get_python_executable
from executors.result_policy import (
    ResultPolicyKeys,
    build_cancelled_extra,
    build_policy_extra,
    has_non_retryable_policy,
)


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
    cancelled_extra = build_cancelled_extra()
    assert cancelled_extra[ResultPolicyKeys.CANCELLED] is True
    assert cancelled_extra[ResultPolicyKeys.NON_RETRYABLE] is True
    assert has_non_retryable_policy(cancelled_extra) is True


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
    assert result.exit_code == -1
    assert result.error_message == "用户取消"
    assert result.extra[ResultPolicyKeys.CANCELLED] is True
    assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
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
    assert result.exit_code == -1
    assert "用户取消" in (result.error_message or "")
    assert result.extra[ResultPolicyKeys.CANCELLED] is True
    assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
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
