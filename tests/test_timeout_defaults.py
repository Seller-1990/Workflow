# -*- coding: utf-8 -*-
"""超时默认值回归测试（M9 默认超时）"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import constants
import executors.python_executor as python_executor
from executors.python_executor import PythonExecutor


def test_python_executor_applies_default_timeout_when_none(monkeypatch, tmp_path: Path):
    """timeout=None 必须替换为 PYTHON_STEP_TIMEOUT，而不是无限等待。

    把默认超时压到 1 秒后运行一个 sleep 5 秒的脚本：
    若 None 被正确替换，进程会在约 1 秒后被超时终止（远早于脚本自然结束）；
    若替换缺失，脚本会跑满 5 秒并以 success=True 结束，断言随之失败。
    """
    script = tmp_path / "sleep_job.py"
    script.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")

    monkeypatch.setattr(python_executor, "PYTHON_STEP_TIMEOUT", 1)
    monkeypatch.setattr(python_executor, "_get_python_executable", lambda: sys.executable)

    result = PythonExecutor().execute(str(script), timeout=None, log_dir=tmp_path / "logs")

    assert result.success is False
    assert "执行超时" in (result.error_message or "")
    # 超时秒数应来自被 monkeypatch 的默认值，证明 None→PYTHON_STEP_TIMEOUT 已生效
    assert "(1秒)" in (result.error_message or "")


def test_python_step_timeout_constant_is_two_hours():
    assert constants.PYTHON_STEP_TIMEOUT == 7200
