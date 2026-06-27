# -*- coding: utf-8 -*-
"""PowerBI 执行器策略测试：发现逻辑、自动刷新、完成证明与进程树清理。

拆分自原 test_executor_policies.py（1000 行硬门槛，纯位置迁移）。
"""

import os
import sys
import threading
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from executors.powerbi_executor import PowerBIExecutor


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
