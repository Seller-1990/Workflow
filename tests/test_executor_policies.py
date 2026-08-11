# -*- coding: utf-8 -*-
"""执行器策略与发现逻辑测试：Python 执行器与结果策略契约。

拆分自原 test_executor_policies.py（1000 行硬门槛，纯位置迁移）：
- 引擎步骤执行与子工作流策略 → test_executor_policies_engine.py
- 共享伪件 → _executor_policy_utils.py
"""

import io
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from executors.base import ExecutorResult
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


class _StagedCommitExecutor:
    """中性假执行器：先触发工作 → 等待异步完成信号 → 再提交结果。

    替代原 Excel 用例（等待异步查询完成后再保存）的通用语义，
    不依赖 COM / 外部工具，仅保留等待-提交顺序、取消与超时的策略断言。
    """

    def __init__(self):
        self.events: list[str] = []
        self._release = threading.Event()

    def complete_async_work(self) -> None:
        self._release.set()

    def execute(
        self,
        script_path,
        args=None,
        cwd=None,
        env=None,
        log_dir=None,
        timeout=None,
        cancel_event=None,
        **kwargs,
    ) -> ExecutorResult:
        self.events.append("triggered")
        started_at = time.perf_counter()
        while not self._release.is_set():
            if cancel_event is not None and cancel_event.is_set():
                return ExecutorResult(
                    success=False,
                    exit_code=-1,
                    error_message="用户取消",
                    extra=build_cancelled_extra(),
                )
            if timeout is not None and time.perf_counter() - started_at > timeout:
                return ExecutorResult(
                    success=False,
                    exit_code=1,
                    error_message=f"等待异步工作完成超时 ({timeout}秒)",
                )
            time.sleep(0.01)
        self.events.append("committed")
        return ExecutorResult(success=True, exit_code=0)


def test_executor_waits_for_async_work_before_committing(tmp_path: Path):
    executor = _StagedCommitExecutor()
    holder: dict = {}

    def run_executor():
        holder["result"] = executor.execute(
            str(tmp_path / "report.xlsx"),
            log_dir=tmp_path / "logs",
            timeout=2,
        )

    thread = threading.Thread(target=run_executor, daemon=True)
    thread.start()
    time.sleep(0.1)
    # 异步工作未完成前只触发不提交（保存）
    assert executor.events == ["triggered"]
    executor.complete_async_work()
    thread.join(timeout=2)

    result = holder["result"]
    assert result.success is True
    assert executor.events == ["triggered", "committed"]


def test_executor_can_cancel_while_async_wait_is_blocked(tmp_path: Path):
    executor = _StagedCommitExecutor()
    cancel_event = threading.Event()
    threading.Thread(target=lambda: (time.sleep(0.05), cancel_event.set()), daemon=True).start()

    started_at = time.perf_counter()
    result = executor.execute(
        str(tmp_path / "blocked.xlsx"),
        log_dir=tmp_path / "logs",
        timeout=2,
        cancel_event=cancel_event,
    )
    elapsed = time.perf_counter() - started_at

    assert result.success is False
    assert result.exit_code == -1
    assert "用户取消" in (result.error_message or "")
    assert result.extra[ResultPolicyKeys.CANCELLED] is True
    assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
    assert elapsed < 1.0
    assert "committed" not in executor.events


def test_executor_times_out_while_async_wait_is_blocked(tmp_path: Path):
    executor = _StagedCommitExecutor()

    started_at = time.perf_counter()
    result = executor.execute(
        str(tmp_path / "timeout.xlsx"),
        log_dir=tmp_path / "logs",
        timeout=0.1,
    )
    elapsed = time.perf_counter() - started_at

    assert result.success is False
    assert "等待异步工作完成超时" in (result.error_message or "")
    assert elapsed < 1.5
    assert executor.events == ["triggered"]


def test_get_python_executable_prefers_python3_before_hardcoded(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("executors.python_executor.shutil.which", lambda name: {"python": None, "python3": "C:/Tools/python3.exe", "py": None}.get(name))

    result = _get_python_executable()

    assert result == "C:/Tools/python3.exe"
