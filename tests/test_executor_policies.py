# -*- coding: utf-8 -*-
"""执行器策略与发现逻辑测试"""

import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
