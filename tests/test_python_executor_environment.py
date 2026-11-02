# -*- coding: utf-8 -*-
"""Python subprocess environment isolation, independent of cleanup outcomes."""

import io
from pathlib import Path

from executors.python_executor import PythonExecutor


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
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.ident = None
            self.join_calls = []
            self.daemon = daemon

        def start(self):
            self.ident = 1
            self.target(*self.args, **self.kwargs)

        def join(self, timeout=None):
            self.join_calls.append(timeout)

        def is_alive(self):
            return False

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
