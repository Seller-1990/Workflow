# -*- coding: utf-8 -*-
"""Step table row cell helper tests."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ui.step_table.row_cells import dependency_display_lines, stage_name_for_step


def test_dependency_display_lines_uses_stage_codes():
    step = SimpleNamespace(get_depends_on=lambda: ["a", "missing", "b"])
    displays, tool_lines = dependency_display_lines(
        step,
        {
            "a": {"code": "S1-1", "stage_name": "抽取", "step_name": "加载"},
            "b": {"code": "S2-1", "stage_name": "", "step_name": "汇总"},
        },
    )

    assert displays == ["S1-1(抽取)", "S2-1"]
    assert tool_lines == ["S1-1(抽取)  ·  加载", "S2-1  ·  汇总"]


def test_dependency_display_lines_logs_bad_dependency_payload(caplog):
    def broken_depends_on():
        raise ValueError("bad json")

    step = SimpleNamespace(id=9, get_depends_on=broken_depends_on)
    with caplog.at_level(logging.WARNING, logger="ui.step_table.row_cells"):
        displays, tool_lines = dependency_display_lines(step, {})

    assert displays == []
    assert tool_lines == []
    assert "读取步骤依赖失败，step_id=9" in caplog.text


def test_stage_name_for_step_matches_cached_stage_uid():
    step = SimpleNamespace(stage_uid="s2")

    assert stage_name_for_step(step, [{"uid": "s1", "name": "抽取"}, {"uid": "s2", "name": "报表"}]) == "报表"
    assert stage_name_for_step(step, []) == ""
