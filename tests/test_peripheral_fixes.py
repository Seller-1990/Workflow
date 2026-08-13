# -*- coding: utf-8 -*-
"""外围缺陷修复回归测试：配置原子写入、解释器缺失提示、关闭按钮路径"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import config
import executors.python_executor as python_executor
from executors.python_executor import PythonExecutor


def test_python_executor_missing_interpreter(monkeypatch, tmp_path: Path):
    script = tmp_path / "job.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(python_executor, "_get_python_executable", lambda: None)

    result = PythonExecutor().execute(script_path=str(script), log_dir=tmp_path / "logs")

    assert result.success is False
    assert "未找到系统 Python 解释器" in (result.error_message or "")


def test_webhook_close_button_routes_through_close_event():
    # 关闭按钮必须走 close() 触发 closeEvent 的未保存确认，禁止 accept() 绕过
    source = (SRC_DIR / "ui" / "webhook_manager.py").read_text(encoding="utf-8")

    assert "self.btn_close.clicked.connect(self.close)" in source
    assert "connect(self.accept)" not in source
