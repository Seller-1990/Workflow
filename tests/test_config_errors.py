# -*- coding: utf-8 -*-
"""配置错误可见性测试"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
from exceptions import ConfigurationError
from models import Step



def test_ensure_directory_raises_clear_error(monkeypatch, tmp_path: Path):
    target = tmp_path / "data"

    def _raise_os_error(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", _raise_os_error)

    try:
        config._ensure_directory(target, "数据目录")
    except RuntimeError as exc:
        assert "无法创建数据目录" in str(exc)
        assert str(target) in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_corrupt_step_dependencies_fail_explicitly():
    step = Step(uid="step", workflow_id=1, name="broken", order=0, depends_on="[broken")

    try:
        step.get_depends_on()
    except ConfigurationError as exc:
        assert "步骤依赖" in str(exc)
        assert "step" in str(exc)
    else:
        raise AssertionError("expected ConfigurationError")

def test_step_type_choices_hide_windows_desktop_automation_on_macos(monkeypatch):
    monkeypatch.setattr(config.sys, "platform", "darwin")

    values = [value for value, _label in config.StepType.choices()]

    assert config.StepType.PYTHON in values
    assert config.StepType.SUB_WORKFLOW in values
    # 退役类型不应出现在选项中
    assert "excel_powerquery" not in values
    assert "powerbi_refresh" not in values