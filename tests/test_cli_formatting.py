# -*- coding: utf-8 -*-
"""Pure CLI formatting contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cli_formatting import format_step_finished_line


def test_step_finished_line_uses_cancel_and_skip_labels():
    assert format_step_finished_line("清洗数据", "cancelled", 1.2) == "  CANCEL [清洗数据] 已取消 · 耗时 1s"
    assert format_step_finished_line("清洗数据", "skipped") == "  SKIP [清洗数据] 已跳过"


def test_step_finished_line_keeps_failure_label_for_unknown_failures():
    assert format_step_finished_line("清洗数据", "failure") == "  FAIL [清洗数据] 状态: failure"
