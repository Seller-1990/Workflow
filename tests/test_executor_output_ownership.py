# -*- coding: utf-8 -*-
"""真实管道和线程验证执行器的输出所有权，而非仅检查失败返回值。"""

import importlib
import io
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from executors.bat_executor import BatExecutor
from executors.python_executor import PythonExecutor
from executors.result_policy import ResultPolicyKeys, has_non_retryable_policy
from run_policy_notes import append_policy_risk_note


_THREAD = threading.Thread
_JOIN = threading.Thread.join
_OPEN = open


class _Pipe:
    def __init__(self, data=b"", *, held=False, read_error=False):
        self.entered = threading.Event()
        self.read_returned = threading.Event()
        self.concurrent_read = threading.Event()
        self.closed_event = threading.Event()
        self.close_thread = None
        self.reader_threads = set()
        self.read_error = read_error
        self.writer = None
        if held:
            reader_fd, writer_fd = os.pipe()
            # BufferedReader.close() 会等待正在 readline 的锁；不能在主线程关闭它。
            self.reader = os.fdopen(reader_fd, "rb")
            self.writer = os.fdopen(writer_fd, "wb", buffering=0)
        else:
            self.reader = io.BytesIO(data)

    def readline(self):
        self.reader_threads.add(threading.get_ident())
        if len(self.reader_threads) > 1:
            self.concurrent_read.set()
        self.entered.set()
        if self.read_error:
            self.read_returned.set()
            raise ValueError("pipe read boom")
        line = self.reader.readline()
        self.read_returned.set()
        return line

    def close(self):
        self.close_thread = threading.get_ident()
        self.reader.close()
        self.closed_event.set()

    def release(self, data=b"LATE_OUTPUT\n"):
        if self.writer is not None and not self.writer.closed:
            try:
                self.writer.write(data)
            except OSError:
                # Windows 已无 reader 时也可能报告 EINVAL，而非 BrokenPipeError。
                pass
            finally:
                self.writer.close()


class _Log:
    def __init__(self, file_obj, *, write_error=False, write_gate=None):
        self.file_obj = file_obj
        self.write_error = write_error
        self.write_gate = write_gate
        self.write_entered = threading.Event()
        self.closed_event = threading.Event()
        self.closed_writes = []
        self.failed_writes = []
        self.operations = []

    def write(self, value):
        self.operations.append(("write", value))
        if value.startswith("EARLY_OUTPUT"):
            self.write_entered.set()
            if self.write_gate is not None:
                assert self.write_gate.wait(3), "test did not release the log writer"
            if self.write_error:
                self.failed_writes.append(value)
                raise OSError("log write boom")
        if self.file_obj.closed:
            self.closed_writes.append(value)
        return self.file_obj.write(value)

    def flush(self):
        self.operations.append(("flush", None))
        return self.file_obj.flush()

    def close(self):
        self.operations.append(("close", None))
        self.file_obj.close()
        self.closed_event.set()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _Console(io.StringIO):
    def __init__(self, write_gate=None):
        super().__init__()
        self.write_gate = write_gate
        self.write_entered = threading.Event()
        self.operations = []

    def write(self, value):
        self.operations.append(("write", value))
        if value.startswith("EARLY_OUTPUT"):
            self.write_entered.set()
            if self.write_gate is not None:
                assert self.write_gate.wait(3), "test did not release the console writer"
        return super().write(value)

    def flush(self):
        self.operations.append(("flush", None))
        return super().flush()


@pytest.fixture(params=[PythonExecutor, BatExecutor], ids=["python", "bat"])
def executor_type(request):
    return request.param


class _Harness:
    def __init__(
        self, monkeypatch, tmp_path, executor_type, *, mode="exit", held=True,
        fail_start=None, read_error=False, write_error=False, write_gate=None,
        exit_code=0, fail_construct=None, fail_after_start=False, kill_error=False,
        held_stream="stdout", console_write_gate=None, stdout_data=b"EARLY_OUTPUT\n",
    ):
        self.executor_type = executor_type
        self.module = importlib.import_module(executor_type.__module__)
        self.mode = mode
        self.script = tmp_path / ("job.py" if executor_type is PythonExecutor else "job.bat")
        self.script.write_text("", encoding="utf-8")
        self.log_dir = tmp_path / "logs"
        self.logs = {}
        self.stdout_sink = _Console(console_write_gate)
        self.stderr_sink = _Console()
        self.stdout = _Pipe(
            stdout_data, held=held and held_stream == "stdout", read_error=read_error,
        )
        self.stderr = _Pipe(b"ERROR_EXCERPT\n", held=held and held_stream == "stderr")
        self.threads = []
        self.hidden_threads = []
        self.thread_errors = []
        self.wait_reached = threading.Event()
        self.kill_calls = []
        self.communicate_calls = []
        self.wait_calls = []
        self.returncode = None
        self.pid = 112233
        self.exit_code = exit_code
        self.kill_error = kill_error
        self.construct_reached = threading.Event()
        harness = self

        class ReaderThread(_THREAD):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.index = len(harness.threads) + 1
                if self.index == fail_construct:
                    harness.construct_reached.set()
                    raise RuntimeError("thread construct boom")
                harness.threads.append(self)

            def start(self):
                if self.index == fail_start and not fail_after_start:
                    raise RuntimeError("thread start boom")
                super().start()
                pipe = harness.stdout if self.index == 1 else harness.stderr
                assert pipe.entered.wait(1), "reader did not enter the real pipe"
                if self.index == fail_start:
                    raise RuntimeError("thread start boom after launch")

            def join(self, timeout=None):
                assert timeout is not None, "reader join must be bounded"
                return super().join(min(timeout, 0.04))

        def tracked_open(path, *args, **kwargs):
            file_obj = _OPEN(path, *args, **kwargs)
            log = _Log(
                file_obj,
                write_error=write_error and Path(path).name == "stdout.txt",
                write_gate=write_gate if Path(path).name == "stdout.txt" else None,
            )
            self.logs[Path(path).name] = log
            return log

        def wait_with_cancel(*args, **kwargs):
            assert self.stdout.entered.wait(1)
            assert self.stderr.entered.wait(1)
            self.wait_reached.set()
            return (False, False) if mode == "timeout" else (True, True)

        monkeypatch.setattr(self.module, "open", tracked_open, raising=False)
        monkeypatch.setattr(self.module, "start_process", lambda *a, **k: self)
        monkeypatch.setattr(self.module.threading, "Thread", ReaderThread)
        monkeypatch.setattr(threading, "excepthook", lambda args: self.thread_errors.append(args.exc_value))
        monkeypatch.setattr(self.module.sys, "stdout", self.stdout_sink)
        monkeypatch.setattr(self.module.sys, "stderr", self.stderr_sink)
        monkeypatch.setattr(executor_type, "STREAM_JOIN_TIMEOUT_SECONDS", 0.04)
        monkeypatch.setattr(executor_type, "PROCESS_WAIT_TIMEOUT_SECONDS", 0.04, raising=False)
        monkeypatch.setattr(executor_type, "wait_with_cancel", staticmethod(wait_with_cancel))
        monkeypatch.setattr(executor_type, "kill_process_tree", staticmethod(self.kill))

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) == 1 and self.mode in ("exit", "wait_error"):
            assert self.stdout.entered.wait(1)
            assert self.stderr.entered.wait(1)
            self.wait_reached.set()
            if self.mode == "wait_error":
                raise RuntimeError("process wait boom")
        if self.mode == "cleanup_wait_error":
            raise subprocess.TimeoutExpired("job", timeout)
        self.returncode = self.exit_code if not self.kill_calls else -9
        return self.returncode

    def communicate(self, timeout=None):
        self.communicate_calls.append(timeout)
        if self.stdout.writer is not None:
            # 模拟 Windows Popen.communicate 的隐藏读取线程，实际与现有 reader 竞争。
            thread = _THREAD(target=self.stdout.readline, daemon=True)
            self.hidden_threads.append(thread)
            thread.start()
            assert self.stdout.concurrent_read.wait(1)
            raise subprocess.TimeoutExpired("job", timeout)
        return b"", b""

    def kill(self, proc, **kwargs):
        assert proc is self
        self.kill_calls.append(self.pid)
        if self.kill_error:
            raise RuntimeError("process kill boom")
        if self.mode != "cleanup_wait_error":
            self.returncode = -9

    def execute(self):
        cancel_event = threading.Event() if self.mode in ("cancel", "timeout", "cleanup_wait_error") else None
        return self.executor_type().execute(
            str(self.script), log_dir=self.log_dir, cancel_event=cancel_event, timeout=1,
        )

    def release_and_join(self):
        self.stdout.release()
        self.stderr.release()
        for thread in self.threads + self.hidden_threads:
            if thread.ident is not None:
                _JOIN(thread, timeout=2)
                assert not thread.is_alive(), "released test reader did not finish"


@pytest.mark.parametrize("mode", ["exit", "cancel", "timeout", "wait_error", "cleanup_wait_error"])
def test_held_pipe_is_detached_before_invocation_completes(monkeypatch, tmp_path, executor_type, mode):
    harness = _Harness(monkeypatch, tmp_path, executor_type, mode=mode)
    try:
        started = time.monotonic()
        result = harness.execute()
        elapsed = time.monotonic() - started
        assert harness.wait_reached.is_set(), "intended parent wait/cancel branch was not reached"
        assert harness.stdout.entered.is_set()
        assert elapsed < 1.5
        before = (harness.log_dir / "stdout.txt").read_bytes()
    finally:
        harness.release_and_join()

    assert result.success is (mode == "exit")
    assert result.exit_code == (0 if mode == "exit" else -1)
    assert harness.kill_calls == ([] if mode == "exit" else [harness.pid])
    assert harness.communicate_calls == [], "cleanup must not create a second pipe reader"
    assert not harness.stdout.concurrent_read.is_set()
    assert harness.thread_errors == []
    assert harness.logs["stdout.txt"].closed_writes == []
    assert "LATE_OUTPUT" not in harness.stdout_sink.getvalue()
    assert before == (harness.log_dir / "stdout.txt").read_bytes()
    assert harness.stdout.closed_event.is_set()
    assert harness.stdout.close_thread == harness.threads[0].ident
    assert harness.stderr.closed_event.is_set()
    assert has_non_retryable_policy(result.extra)
    assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    assert "输出" in result.extra[ResultPolicyKeys.NOTE]
    assert "输出" in result.error_message
    assert "可能仍有后台任务运行" in append_policy_risk_note(result.error_message, result.extra)
    if mode in ("cancel", "cleanup_wait_error"):
        assert result.extra[ResultPolicyKeys.CANCELLED] is True
        assert result.error_message.startswith("用户取消")
    elif mode == "timeout":
        assert result.error_message.startswith("执行超时 (1秒)")
    elif mode == "wait_error":
        assert "process wait boom" in result.error_message


@pytest.mark.parametrize("mode", ["exit", "cancel", "timeout"])
def test_held_stderr_is_also_detached_before_late_output(
    monkeypatch, tmp_path, executor_type, mode,
):
    harness = _Harness(monkeypatch, tmp_path, executor_type, mode=mode, held_stream="stderr")
    try:
        result = harness.execute()
        assert harness.wait_reached.is_set()
        assert harness.stderr.entered.is_set()
        before = (harness.log_dir / "stderr.txt").read_bytes()
    finally:
        harness.release_and_join()

    assert result.success is (mode == "exit")
    assert "LATE_OUTPUT" not in harness.stderr_sink.getvalue()
    assert before == (harness.log_dir / "stderr.txt").read_bytes()
    assert harness.logs["stderr.txt"].closed_writes == []
    assert harness.stderr.closed_event.is_set()
    assert harness.stderr.close_thread == harness.threads[1].ident
    assert harness.thread_errors == []
    assert harness.communicate_calls == []
    assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    assert has_non_retryable_policy(result.extra)


def test_incomplete_capture_remains_reported_if_reader_finishes_during_detach(
    monkeypatch, tmp_path, executor_type,
):
    from executors.output_capture import _PipeCapture

    harness = _Harness(monkeypatch, tmp_path, executor_type)
    detach = _PipeCapture.detach
    late_output_released = threading.Event()

    def detach_after_stdout_finishes(stream):
        if stream.name == "stderr":
            harness.stdout.release()
            _JOIN(harness.threads[0], timeout=1)
            assert not harness.threads[0].is_alive()
            late_output_released.set()
        return detach(stream)

    monkeypatch.setattr(_PipeCapture, "detach", detach_after_stdout_finishes)
    try:
        result = harness.execute()
    finally:
        harness.release_and_join()

    assert harness.wait_reached.is_set()
    assert late_output_released.is_set()
    assert "LATE_OUTPUT" not in harness.stdout_sink.getvalue()
    assert "LATE_OUTPUT" not in (harness.log_dir / "stdout.txt").read_text(encoding="utf-8-sig")
    assert result.success is True
    assert has_non_retryable_policy(result.extra)
    assert "输出采集不完整" in result.error_message


@pytest.mark.parametrize("fail_start", [1, 2])
def test_partial_thread_start_failure_stays_inside_log_ownership(
    monkeypatch, tmp_path, executor_type, fail_start,
):
    harness = _Harness(monkeypatch, tmp_path, executor_type, fail_start=fail_start)
    try:
        result = harness.execute()
        assert len(harness.threads) >= fail_start
        if fail_start == 2:
            assert harness.stdout.entered.is_set(), "first reader must really be blocked"
    finally:
        harness.release_and_join()

    assert result.success is False
    assert "thread start boom" in result.error_message
    assert "cannot join thread before it is started" not in result.error_message
    assert harness.kill_calls == [harness.pid]
    assert harness.communicate_calls == []
    assert harness.thread_errors == []
    assert all(log.closed_event.is_set() for log in harness.logs.values())
    assert all(not log.closed_writes for log in harness.logs.values())
    assert harness.stdout.closed_event.is_set()
    assert harness.stderr.closed_event.is_set()
    assert has_non_retryable_policy(result.extra)


@pytest.mark.parametrize("fail_construct", [1, 2])
def test_thread_construction_failure_releases_unowned_pipes(
    monkeypatch, tmp_path, executor_type, fail_construct,
):
    harness = _Harness(monkeypatch, tmp_path, executor_type, fail_construct=fail_construct)
    try:
        result = harness.execute()
    finally:
        harness.release_and_join()

    assert harness.construct_reached.is_set()
    if fail_construct == 2:
        assert harness.stdout.entered.is_set()
    assert "thread construct boom" in result.error_message
    assert result.success is False
    assert harness.kill_calls == [harness.pid]
    assert harness.communicate_calls == []
    assert harness.stdout.closed_event.is_set()
    assert harness.stderr.closed_event.is_set()
    assert all(log.closed_event.is_set() for log in harness.logs.values())
    assert all(not log.closed_writes for log in harness.logs.values())
    assert harness.thread_errors == []
    assert has_non_retryable_policy(result.extra)


def test_start_exception_after_launch_still_respects_reader_ownership(
    monkeypatch, tmp_path, executor_type,
):
    harness = _Harness(
        monkeypatch, tmp_path, executor_type, fail_start=1, fail_after_start=True,
    )
    try:
        result = harness.execute()
    finally:
        harness.release_and_join()

    assert harness.stdout.entered.is_set()
    assert "thread start boom after launch" in result.error_message
    assert harness.stdout.close_thread == harness.threads[0].ident
    assert harness.kill_calls == [harness.pid]
    assert harness.communicate_calls == []
    assert harness.thread_errors == []
    assert harness.logs["stdout.txt"].closed_writes == []
    assert has_non_retryable_policy(result.extra)


def test_kill_failure_does_not_skip_detach_or_lose_cancellation(
    monkeypatch, tmp_path, executor_type,
):
    harness = _Harness(monkeypatch, tmp_path, executor_type, mode="cancel", kill_error=True)
    try:
        result = harness.execute()
    finally:
        harness.release_and_join()

    assert harness.wait_reached.is_set()
    assert harness.kill_calls == [harness.pid]
    assert harness.wait_calls == [executor_type.PROCESS_WAIT_TIMEOUT_SECONDS]
    assert result.success is False
    assert result.error_message.startswith("用户取消")
    assert "process kill boom" in result.error_message
    assert result.extra[ResultPolicyKeys.CANCELLED] is True
    assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
    assert harness.communicate_calls == []
    assert harness.stdout.closed_event.is_set()
    assert harness.stderr.closed_event.is_set()
    assert harness.thread_errors == []
    assert all(log.closed_event.is_set() for log in harness.logs.values())
    assert all(not log.closed_writes for log in harness.logs.values())


@pytest.mark.parametrize("failure", ["read", "write"])
def test_reader_exceptions_close_handles_and_report_incomplete_output(
    monkeypatch, tmp_path, executor_type, failure,
):
    harness = _Harness(
        monkeypatch, tmp_path, executor_type, held=False,
        read_error=failure == "read", write_error=failure == "write",
    )
    try:
        result = harness.execute()
    finally:
        harness.release_and_join()

    assert harness.wait_reached.is_set()
    assert harness.stdout.read_returned.is_set()
    if failure == "write":
        assert harness.logs["stdout.txt"].failed_writes == ["EARLY_OUTPUT\n"]
    assert result.success is True, "capture errors must not invent a parent-process failure"
    assert result.exit_code == 0
    assert harness.kill_calls == []
    assert harness.thread_errors == []
    assert harness.stdout.closed_event.is_set()
    assert harness.stderr.closed_event.is_set()
    assert all(log.closed_event.is_set() for log in harness.logs.values())
    assert has_non_retryable_policy(result.extra)
    assert result.extra[ResultPolicyKeys.MANUAL_REQUIRED] is True
    assert f"{'pipe read' if failure == 'read' else 'log write'} boom" in result.error_message


@pytest.mark.parametrize("failure", ["second_open", "header", "spawn"])
def test_log_setup_failures_close_previously_opened_files(
    monkeypatch, tmp_path, executor_type, failure,
):
    module = importlib.import_module(executor_type.__module__)
    script = tmp_path / ("setup.py" if executor_type is PythonExecutor else "setup.bat")
    script.write_text("", encoding="utf-8")
    reached = threading.Event()
    files = []
    spawn_calls = []

    class SetupLog(_Log):
        def write(self, value):
            if failure == "header":
                reached.set()
                raise OSError("header write boom")
            return super().write(value)

    def tracked_open(path, *args, **kwargs):
        if failure == "second_open" and Path(path).name == "stderr.txt":
            reached.set()
            raise OSError("second log open boom")
        log = SetupLog(_OPEN(path, *args, **kwargs))
        files.append(log)
        return log

    def spawn(*args, **kwargs):
        spawn_calls.append(1)
        reached.set()
        raise OSError("process spawn boom")

    monkeypatch.setattr(module, "open", tracked_open, raising=False)
    monkeypatch.setattr(module, "start_process", spawn)
    result = executor_type().execute(str(script), log_dir=tmp_path / "logs")

    assert reached.is_set()
    assert result.success is False
    assert "boom" in result.error_message
    assert files and all(log.closed_event.is_set() for log in files)
    assert all(not log.closed_writes for log in files)
    assert spawn_calls == ([1] if failure == "spawn" else [])


@pytest.mark.parametrize("sink", ["log", "console"])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel", "timeout"])
def test_execute_returns_before_inflight_sink_is_released(
    monkeypatch, tmp_path, executor_type, sink, outcome,
):
    from executors.output_capture import _PipeCapture

    release_write = threading.Event()
    finished = threading.Event()
    detach_entered = threading.Event()
    holder = {}
    mode = outcome if outcome in ("cancel", "timeout") else "exit"
    harness = _Harness(
        monkeypatch, tmp_path, executor_type, held=False, mode=mode,
        exit_code=7 if outcome == "failure" else 0,
        write_gate=release_write if sink == "log" else None,
        console_write_gate=release_write if sink == "console" else None,
        stdout_data=b"EARLY_OUTPUT\nAFTER_DETACH\n",
    )
    detach = _PipeCapture.detach

    def tracked_detach(stream):
        if stream.name == "stdout":
            detach_entered.set()
        return detach(stream)

    monkeypatch.setattr(_PipeCapture, "detach", tracked_detach)

    def execute():
        try:
            holder["result"] = harness.execute()
        finally:
            finished.set()

    runner = _THREAD(target=execute, daemon=True)
    runner.start()
    try:
        assert harness.wait_reached.wait(1), "parent outcome branch was not reached"
        log = harness.logs["stdout.txt"]
        blocked_sink = log if sink == "log" else harness.stdout_sink
        assert blocked_sink.write_entered.wait(1), "sink write gate was not reached"
        assert detach_entered.wait(1), "capture finish never reached detachment"
        # 必须在释放在途 I/O 之前验证实际 execute() 返回，不能由 finally 掩盖。
        assert finished.wait(0.5), "execute() blocked on an in-flight sink after its bounded join"
        assert not release_write.is_set()
        _JOIN(runner, timeout=0.1)
        assert not runner.is_alive()
        if sink == "log":
            assert ("close", None) not in log.operations, "log close overlapped an in-flight write"
            assert not log.closed_event.is_set(), "log closed while its write was still in flight"
        operations_at_return = (
            [op for op in log.operations if op[0] != "close"],
            list(harness.stdout_sink.operations),
        )
        result = holder["result"]
        assert result.success is (outcome == "success")
        assert result.exit_code == (7 if outcome == "failure" else 0 if outcome == "success" else -1)
        assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
        assert has_non_retryable_policy(result.extra)
        assert "输出采集不完整" in result.error_message
        assert "可能仍有后台任务运行" in append_policy_risk_note(result.error_message, result.extra)
        if outcome == "cancel":
            assert result.extra[ResultPolicyKeys.CANCELLED] is True
            assert result.error_message.startswith("用户取消")
        elif outcome == "timeout":
            assert result.error_message.startswith("执行超时 (1秒)")
        elif outcome == "failure":
            assert "退出码: 7" in result.error_message
            assert "ERROR_EXCERPT" in result.error_message
    finally:
        release_write.set()
        assert finished.wait(2), "executor remained blocked after releasing the writer"
        _JOIN(runner, timeout=1)
        harness.release_and_join()

    assert all(log.closed_event.is_set() for log in harness.logs.values())
    assert log.closed_writes == []
    assert harness.thread_errors == []
    assert operations_at_return == (
        [op for op in log.operations if op[0] != "close"],
        list(harness.stdout_sink.operations),
    ), "detachment authorized a new sink write/flush after execute() returned"
    assert "EARLY_OUTPUT" in (harness.log_dir / "stdout.txt").read_text(encoding="utf-8-sig")
    assert "AFTER_DETACH" not in harness.stdout_sink.getvalue()
    assert "AFTER_DETACH" not in (harness.log_dir / "stdout.txt").read_text(encoding="utf-8-sig")
    assert harness.kill_calls == ([] if outcome in ("success", "failure") else [harness.pid])
    assert harness.communicate_calls == []


@pytest.mark.parametrize("exit_code", [0, 7])
def test_completed_readers_release_pipes_and_keep_stderr_excerpt(
    monkeypatch, tmp_path, executor_type, exit_code,
):
    harness = _Harness(monkeypatch, tmp_path, executor_type, held=False, exit_code=exit_code)
    try:
        result = harness.execute()
    finally:
        harness.release_and_join()

    assert harness.wait_reached.is_set()
    assert result.success is (exit_code == 0)
    assert result.exit_code == exit_code
    assert result.extra == {}
    assert harness.kill_calls == []
    assert harness.communicate_calls == []
    assert harness.thread_errors == []
    assert harness.stdout.closed_event.is_set()
    assert harness.stderr.closed_event.is_set()
    assert harness.stdout.close_thread == harness.threads[0].ident
    assert harness.stderr.close_thread == harness.threads[1].ident
    if exit_code:
        assert "ERROR_EXCERPT" in result.error_message
    else:
        assert result.error_message is None


@pytest.mark.parametrize("exit_code", [0, 9])
def test_real_parent_exit_does_not_kill_intentional_descendant_or_mutate_finished_logs(
    monkeypatch, tmp_path, executor_type, exit_code,
):
    if executor_type is BatExecutor and sys.platform != "win32":
        pytest.skip("real cmd.exe execution requires Windows")
    module = importlib.import_module(executor_type.__module__)
    reached = tmp_path / "descendant-ready"
    release = tmp_path / "release-descendant"
    child_script = tmp_path / "child.py"
    child_script.write_text(
        "import pathlib, sys, time\n"
        "ready, release = map(pathlib.Path, sys.argv[1:])\n"
        "print('EARLY_OUTPUT', flush=True)\n"
        "ready.write_text('ready', encoding='utf-8')\n"
        "deadline = time.monotonic() + 8\n"
        "while not release.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "print('LATE_OUTPUT', flush=True)\n",
        encoding="utf-8",
    )
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child, ready, release, exit_code = sys.argv[1:]\n"
        "subprocess.Popen([sys.executable, '-u', child, ready, release])\n"
        "deadline = time.monotonic() + 5\n"
        "while not pathlib.Path(ready).exists():\n"
        "    if time.monotonic() > deadline: raise RuntimeError('child never ready')\n"
        "    time.sleep(0.01)\n"
        "print('ERROR_EXCERPT', file=sys.stderr, flush=True)\n"
        "sys.exit(int(exit_code))\n",
        encoding="utf-8",
    )
    if executor_type is BatExecutor:
        script = tmp_path / "parent.bat"
        script.write_text(
            f'@echo off\n"{sys.executable}" -u "{parent_script}" "{child_script}" '
            f'"{reached}" "{release}" {exit_code}\nexit /b %errorlevel%\n',
            encoding="utf-8",
        )
        args = None
    else:
        script = parent_script
        args = [str(child_script), str(reached), str(release), str(exit_code)]

    threads = []
    closed = []
    errors = []
    killed = []
    stdout_sink, stderr_sink = io.StringIO(), io.StringIO()
    from executors.output_capture import _PipeCapture
    close_pipe = _PipeCapture._close_pipe

    class ReaderThread(_THREAD):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)

    def tracked_close(stream):
        close_pipe(stream)
        closed.append(stream.pipe.closed)

    monkeypatch.setattr(module.threading, "Thread", ReaderThread)
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    monkeypatch.setattr(module.sys, "stdout", stdout_sink)
    monkeypatch.setattr(module.sys, "stderr", stderr_sink)
    monkeypatch.setattr(executor_type, "STREAM_JOIN_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(executor_type, "kill_process_tree", staticmethod(lambda proc: killed.append(proc.pid)))
    monkeypatch.setattr(_PipeCapture, "_close_pipe", tracked_close)
    try:
        started = time.monotonic()
        result = executor_type().execute(str(script), args=args, log_dir=tmp_path / "logs", timeout=5)
        elapsed = time.monotonic() - started
        assert reached.exists(), "actual descendant output/hold branch was not reached"
        assert elapsed < 3
        assert len(threads) == 2
        assert any(thread.is_alive() for thread in threads), "descendant did not retain the inherited pipes"
        before = [(tmp_path / "logs" / name).read_bytes() for name in ("stdout.txt", "stderr.txt")]
    finally:
        release.write_text("release", encoding="utf-8")
        for thread in threads:
            _JOIN(thread, timeout=3)
            assert not thread.is_alive(), "actual descendant did not release its inherited pipes"

    assert result.success is (exit_code == 0)
    assert result.exit_code == exit_code
    assert killed == []
    assert errors == []
    assert closed == [True, True]
    assert "EARLY_OUTPUT" in stdout_sink.getvalue()
    assert "LATE_OUTPUT" not in stdout_sink.getvalue()
    assert before == [(tmp_path / "logs" / name).read_bytes() for name in ("stdout.txt", "stderr.txt")]
    assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    assert has_non_retryable_policy(result.extra)
    assert "输出采集不完整" in result.error_message
    if exit_code:
        assert "ERROR_EXCERPT" in result.error_message
