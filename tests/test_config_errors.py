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


def test_load_user_config_logs_invalid_json(monkeypatch, tmp_path: Path, caplog):
    broken_config = tmp_path / "config.json"
    broken_config.write_text("{invalid json", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", broken_config)

    with caplog.at_level(logging.WARNING, logger="config"):
        loaded = config.load_user_config()

    assert loaded == {}
    assert "加载用户配置失败" in caplog.text
    assert str(broken_config) in caplog.text


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
    assert config.StepType.EXCEL_POWERQUERY not in values
    assert config.StepType.POWERBI_REFRESH not in values