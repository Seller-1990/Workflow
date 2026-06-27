# -*- coding: utf-8 -*-
"""Step table view-model helper tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ui.step_table.view_model import (
    build_prev_by_id,
    build_row_meta,
    build_stage_records,
    build_stage_render_context,
    build_single_script_uid_display_map,
    ensure_default_stage_records,
    sort_steps_by_stage,
)


def _step(step_id: int, uid: str, name: str, order: int, stage_uid: str):
    return SimpleNamespace(id=step_id, uid=uid, name=name, order=order, stage_uid=stage_uid)


def test_build_stage_records_and_default_fallback():
    stages, index_by_uid = build_stage_records([
        SimpleNamespace(uid="s1", name="抽取", order=2, color="#fff"),
        SimpleNamespace(uid="s2", name="报表", order=5, color=None),
    ])

    assert stages == [
        {"uid": "s1", "name": "抽取", "order": 2, "color": "#fff"},
        {"uid": "s2", "name": "报表", "order": 5, "color": None},
    ]
    assert index_by_uid == {"s1": 0, "s2": 1}
    assert ensure_default_stage_records([]) == (
        [{"uid": "", "name": "默认阶段", "order": 0, "color": None}],
        {"": 0},
    )


def test_sort_steps_and_build_row_meta_by_stage():
    steps = [
        _step(3, "c", "C", 1, "s2"),
        _step(1, "a", "A", 1, "s1"),
        _step(2, "b", "B", 0, "s2"),
    ]

    sorted_steps = sort_steps_by_stage(steps, {"s1": 0, "s2": 1})
    rows = build_row_meta(
        sorted_steps,
        [{"uid": "s1", "name": "抽取"}, {"uid": "s2", "name": "报表"}],
        single_script_mode=False,
    )

    assert [step.id for step in sorted_steps] == [1, 2, 3]
    assert rows == [
        {"kind": "stage_header", "stage_uid": "s1"},
        {"kind": "step", "step_id": 1, "stage_uid": "s1"},
        {"kind": "stage_header", "stage_uid": "s2"},
        {"kind": "step", "step_id": 2, "stage_uid": "s2"},
        {"kind": "step", "step_id": 3, "stage_uid": "s2"},
    ]
    assert build_prev_by_id(sorted_steps)[3].id == 2


def test_display_maps_are_stable_for_single_and_stage_modes():
    steps = [
        _step(1, "a", "A", 0, "s1"),
        _step(2, "b", "B", 1, "s1"),
    ]

    assert build_single_script_uid_display_map(steps)["b"]["code"] == "S1-2"

    context = build_stage_render_context(steps, [{"uid": "s1", "name": "抽取"}])

    assert context["stage_display_index"] == {"s1": 0}
    assert context["within_idx_by_step"][("s1", 2)] == 1
    assert context["uid_display_map"]["b"]["code"] == "S1-2"
