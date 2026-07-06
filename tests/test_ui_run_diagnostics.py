# -*- coding: utf-8 -*-
"""Run-history diagnostic text tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / "src" / "ui" / "run_diagnostics.py"
spec = importlib.util.spec_from_file_location("ui_run_diagnostics_under_test", MODULE_PATH)
run_diagnostics = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(run_diagnostics)


def test_cancelled_run_diagnostic_mentions_pending_cleanup():
    text = run_diagnostics.build_run_diagnostic(
        "cancelled",
        {"cancelled": 2, "running": 1, "pending": 1},
    )

    assert "停止请求已送达" in text
    assert "2 个步骤" in text


def test_failure_run_diagnostic_uses_failure_count():
    text = run_diagnostics.build_run_diagnostic("failure", {"failure": 3})

    assert text == "运行失败，3 个步骤失败"


def test_failure_run_diagnostic_surfaces_background_risk():
    text = run_diagnostics.build_run_diagnostic(
        "failure",
        {"failure": 1, "manual_required": 1, "background_risk": 1, "orphan_risk": 1},
    )

    assert "需要人工确认" in text
    assert "后台任务" in text
    assert "子工作流" in text


def test_success_run_diagnostic_is_stable_without_counts():
    text = run_diagnostics.build_run_diagnostic("success", None)

    assert text == "运行成功，所有必要步骤已完成"
