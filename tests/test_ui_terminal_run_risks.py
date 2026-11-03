# -*- coding: utf-8 -*-
"""Run-history diagnostic text tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parent.parent / "src" / "ui" / "run_diagnostics.py"
spec = importlib.util.spec_from_file_location("ui_run_diagnostics_under_test", MODULE_PATH)
run_diagnostics = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(run_diagnostics)




def test_failure_run_diagnostic_surfaces_background_risk():
    text = run_diagnostics.build_run_diagnostic(
        "failure",
        {"failure": 1, "manual_required": 1, "background_risk": 1, "orphan_risk": 1},
    )

    assert "需要人工确认" in text
    assert "后台任务" in text
    assert "子工作流" in text


@pytest.mark.parametrize(
    ("status", "counts", "expected_prefix"),
    [
        ("success", {}, "运行成功，所有必要步骤已完成"),
        (
            "cancelled", {"cancelled": 2, "running": 1, "pending": 1},
            "停止请求已送达，仍有 2 个步骤等待取消收尾",
        ),
        ("cancelled", {"cancelled": 2}, "已取消，2 个未完成步骤已标记为取消"),
        ("cancelled", {}, "已取消"),
    ],
    ids=["success", "cancel-pending-cleanup", "cancelled-steps", "cancel-no-unfinished"],
)
@pytest.mark.parametrize(
    ("risk_counts", "expected_risk"),
    [
        ({"manual_required": 1}, "1 个步骤需要人工确认"),
        ({"background_risk": 2}, "2 个步骤可能仍有后台任务"),
        ({"orphan_risk": 3}, "3 个子工作流可能仍在后台运行"),
        (
            {"manual_required": 1, "background_risk": 2, "orphan_risk": 3},
            "1 个步骤需要人工确认；2 个步骤可能仍有后台任务；3 个子工作流可能仍在后台运行",
        ),
    ],
    ids=["manual", "background", "orphan", "combined"],
)
def test_terminal_run_diagnostic_preserves_known_risk(
    status, counts, expected_prefix, risk_counts, expected_risk,
):
    text = run_diagnostics.build_run_diagnostic(status, {**counts, **risk_counts})

    assert text == f"{expected_prefix}；{expected_risk}"
    if risk_counts.get("background_risk") or risk_counts.get("orphan_risk"):
        assert "未发现残留运行步骤" not in text


@pytest.mark.parametrize(
    ("status", "counts", "expected"),
    [
        ("success", None, "运行成功，所有必要步骤已完成"),
        ("success", {}, "运行成功，所有必要步骤已完成"),
        ("cancelled", {"running": 1, "pending": 2}, "停止请求已送达，仍有 3 个步骤等待取消收尾"),
        ("cancelled", {"cancelled": 2}, "已取消，2 个未完成步骤已标记为取消"),
        ("cancelled", None, "已取消，未发现残留运行步骤"),
        ("failure", {"failure": 3}, "运行失败，3 个步骤失败"),
        ("failure", {}, "运行失败，未找到失败步骤摘要"),
        ("running", None, "运行中，正在等待步骤状态回写"),
        ("pending", None, "等待运行开始"),
        ("", None, "等待运行开始"),
        ("unknown", {}, "等待运行开始"),
    ],
)
def test_run_diagnostic_preserves_exact_no_risk_text(status, counts, expected):
    assert run_diagnostics.build_run_diagnostic(status, counts) == expected
