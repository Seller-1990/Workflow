# -*- coding: utf-8 -*-
"""执行器运行时清理测试"""

import io
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from executors.python_executor import PythonExecutor
from executors.result_policy import ResultPolicyKeys
from executors.sub_workflow_executor import SubWorkflowExecutor


def _patch_sub_workflow_dependencies(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    monkeypatch.setattr(
        "executors.sub_workflow_executor.get_workflow_by_uid",
        lambda uid: target if uid == "wf-target" else None,
    )
    monkeypatch.setattr(
        "executors.sub_workflow_executor.get_workflow_by_id",
        lambda workflow_id: parent if workflow_id == 1 else None,
    )
    monkeypatch.setattr(
        "executors.sub_workflow_executor.has_cross_workflow_cycle",
        lambda parent_id, target_uid: False,
    )


def test_sub_workflow_executor_fails_fast_when_runner_lacks_cancel_event(monkeypatch):
    _patch_sub_workflow_dependencies(monkeypatch)
    calls = []

    def workflow_runner(workflow_id, reason="manual"):
        calls.append((workflow_id, reason))
        return True

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        workflow_runner=workflow_runner,
    )

    assert result.success is False
    assert result.exit_code == 1
    assert result.error_message == "子工作流运行器必须显式支持 cancel_event 参数"
    assert calls == []


def test_sub_workflow_executor_cancel_confirms_child_exit(monkeypatch):
    _patch_sub_workflow_dependencies(monkeypatch)
    outer_cancel = threading.Event()
    nested_cancel_events = []

    def workflow_runner(workflow_id, reason="manual", cancel_event=None):
        nested_cancel_events.append(cancel_event)
        cancel_event.wait(1.0)
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
    assert result.exit_code == -1
    assert result.error_message == "用户取消"
    assert result.extra[ResultPolicyKeys.CANCELLED] is True
    assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
    assert elapsed < 0.4
    assert nested_cancel_events
    assert nested_cancel_events[0] is not None
    assert nested_cancel_events[0].is_set() is True


def test_sub_workflow_executor_timeout_marks_orphan_risk(monkeypatch):
    _patch_sub_workflow_dependencies(monkeypatch)
    monkeypatch.setattr(SubWorkflowExecutor, "CHILD_EXIT_GRACE_SECONDS", 0.05)
    nested_cancel_events = []

    def workflow_runner(workflow_id, reason="manual", cancel_event=None):
        nested_cancel_events.append(cancel_event)
        time.sleep(0.3)
        return False

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        timeout=0.01,
        workflow_runner=workflow_runner,
    )

    assert result.success is False
    assert result.exit_code == -1
    assert "子工作流执行超时" in (result.error_message or "")
    assert "后台运行风险" in (result.error_message or "")
    assert result.extra[ResultPolicyKeys.ORPHAN_RISK] is True
    assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    assert result.extra[ResultPolicyKeys.CHILD_EXIT_GRACE_SECONDS] == 0.05
    assert nested_cancel_events
    assert nested_cancel_events[0] is not None
    assert nested_cancel_events[0].is_set() is True


def test_python_executor_timeout_cleans_up_process_resources(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    killed = {}

    class DummyProc:
        def __init__(self):
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.pid = 4343
            self.returncode = None
            self.communicate_calls = []
            self.wait_calls = []

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls.append(timeout)
            self.returncode = -1
            return self.returncode

        def communicate(self, timeout=None):
            self.communicate_calls.append(timeout)
            return b"", b""

    class DummyThread:
        instances = []

        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon
            self.started = False
            self.join_calls = []
            self.__class__.instances.append(self)

        def start(self):
            self.started = True

        def join(self, timeout=None):
            self.join_calls.append(timeout)

    proc = DummyProc()
    monkeypatch.setattr("executors.python_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr("executors.python_executor.threading.Thread", DummyThread)
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
        cancel_event=threading.Event(),
        timeout=1,
    )

    assert result.success is False
    assert result.error_message == "执行超时 (1秒)"
    assert killed["pid"] == 4343
    assert proc.communicate_calls == [PythonExecutor.COMMUNICATE_TIMEOUT_SECONDS]
    assert all(thread.started for thread in DummyThread.instances)
    assert all(thread.daemon for thread in DummyThread.instances)
    assert [thread.join_calls for thread in DummyThread.instances] == [
        [PythonExecutor.STREAM_JOIN_TIMEOUT_SECONDS],
        [PythonExecutor.STREAM_JOIN_TIMEOUT_SECONDS],
    ]
    assert proc.wait_calls == []


def test_python_executor_cleans_process_when_output_thread_start_fails(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    killed = []

    class DummyProc:
        def __init__(self):
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.pid = 5656
            self.returncode = None
            self.communicate_calls = []

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -1
            return self.returncode

        def communicate(self, timeout=None):
            self.communicate_calls.append(timeout)
            return b"", b""

    class DummyThread:
        instances = []

        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.started = False
            self.join_calls = []
            self.daemon = daemon
            self.__class__.instances.append(self)

        def start(self):
            if len(self.__class__.instances) == 2:
                raise RuntimeError("thread start boom")
            self.started = True

        def join(self, timeout=None):
            self.join_calls.append(timeout)

    proc = DummyProc()
    monkeypatch.setattr("executors.python_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr("executors.python_executor.threading.Thread", DummyThread)
    monkeypatch.setattr(
        PythonExecutor,
        "kill_process_tree",
        staticmethod(lambda proc, taskkill_timeout=10, wait_timeout=5: killed.append(proc.pid)),
    )

    result = PythonExecutor().execute(str(script), log_dir=tmp_path / "logs", timeout=5)

    assert result.success is False
    assert "thread start boom" in (result.error_message or "")
    assert killed == [5656]
    assert proc.communicate_calls == [PythonExecutor.COMMUNICATE_TIMEOUT_SECONDS]
    assert [thread.join_calls for thread in DummyThread.instances] == [
        [PythonExecutor.STREAM_JOIN_TIMEOUT_SECONDS],
        [PythonExecutor.STREAM_JOIN_TIMEOUT_SECONDS],
    ]


def test_python_executor_cleanup_joins_threads_when_communicate_raises_unexpected_error(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    killed = {}

    class DummyProc:
        def __init__(self):
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.pid = 5454
            self.returncode = None
            self.communicate_calls = []

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = -1
            return self.returncode

        def communicate(self, timeout=None):
            self.communicate_calls.append(timeout)
            raise ValueError("pipe already closed")

    class DummyThread:
        instances = []

        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon
            self.started = False
            self.join_calls = []
            self.__class__.instances.append(self)

        def start(self):
            self.started = True

        def join(self, timeout=None):
            self.join_calls.append(timeout)

    proc = DummyProc()
    monkeypatch.setattr("executors.python_executor.subprocess.Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr("executors.python_executor.threading.Thread", DummyThread)
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
        cancel_event=threading.Event(),
        timeout=1,
    )

    assert result.success is False
    assert result.error_message == "执行超时 (1秒)"
    assert killed["pid"] == 5454
    assert proc.communicate_calls == [PythonExecutor.COMMUNICATE_TIMEOUT_SECONDS]
    assert all(thread.started for thread in DummyThread.instances)
    assert all(thread.daemon for thread in DummyThread.instances)
    assert [thread.join_calls for thread in DummyThread.instances] == [
        [PythonExecutor.STREAM_JOIN_TIMEOUT_SECONDS],
        [PythonExecutor.STREAM_JOIN_TIMEOUT_SECONDS],
    ]



def test_python_executor_sanitizes_subprocess_env(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')", encoding="utf-8")
    captured = {}

    class DummyProc:
        def __init__(self):
            self.stdout = io.BytesIO(b"")
            self.stderr = io.BytesIO(b"")
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    class DummyThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self.join_calls = []
            self.daemon = daemon

        def start(self):
            pass

        def join(self, timeout=None):
            self.join_calls.append(timeout)

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return DummyProc()

    monkeypatch.setenv("PYTHONPATH", "bad-path")
    monkeypatch.setenv("PYTHONHOME", "bad-home")
    monkeypatch.setattr("executors.python_executor.subprocess.Popen", fake_popen)
    monkeypatch.setattr("executors.python_executor.threading.Thread", DummyThread)

    result = PythonExecutor().execute(
        str(script),
        log_dir=tmp_path / "logs",
        env={"PYTHONPATH": "override-bad", "CUSTOM_OK": "1"},
    )

    assert result.success is True
    assert "PYTHONPATH" not in captured["env"]
    assert "PYTHONHOME" not in captured["env"]
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONUNBUFFERED"] == "1"
    assert captured["env"]["CUSTOM_OK"] == "1"
    assert captured["env"]["WORKFLOW_STEP_LOG_DIR"] == str(tmp_path / "logs")
