# -*- coding: utf-8 -*-
"""工作台看板阶段交互测试"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel

import ui.workbench_board as board_module
from ui.workbench_board import (
    STAGE_LANE_BORDER_HEIGHT,
    STAGE_LANE_GAP,
    STAGE_LANE_MIN_HEIGHT,
    STAGE_LANE_MIN_WIDTH,
    WorkbenchBoardPanel,
)


@dataclass
class DummyStage:
    uid: str
    name: str
    order: int
    color: str = ""


@dataclass
class DummyStep:
    id: int
    uid: str
    name: str
    stage_uid: str
    order: int
    step_type: str = "python"
    script_path: str = "script.py"
    is_gate: bool = False
    is_parallel: bool = False

    def get_depends_on(self) -> list[str]:
        return []


def _panel_with_dummy_workflow(monkeypatch) -> WorkbenchBoardPanel:
    stages = [
        DummyStage("stage-a", "准备", 1),
        DummyStage("stage-b", "处理", 2),
        DummyStage("stage-c", "交付", 3),
    ]
    steps = [
        DummyStep(1, "step-1", "提取", "stage-a", 1),
        DummyStep(2, "step-2", "清洗", "stage-a", 2),
        DummyStep(3, "step-3", "汇总", "stage-b", 1),
    ]

    monkeypatch.setattr(board_module, "list_stages", lambda workflow_id: stages)
    monkeypatch.setattr(board_module, "get_steps_by_workflow", lambda workflow_id: steps)
    monkeypatch.setattr(board_module, "get_workflow_by_id", lambda workflow_id: object())
    monkeypatch.setattr(
        board_module,
        "get_stage_order_map",
        lambda workflow_id: {stage.uid: stage.order for stage in stages},
    )
    monkeypatch.setattr(
        board_module.WorkflowEngine,
        "compute_batches",
        staticmethod(lambda workflow, workflow_steps, stage_map: [[step] for step in workflow_steps]),
    )

    panel = WorkbenchBoardPanel()
    panel.load_workflow(100)
    return panel


def test_stage_progress_tracks_step_statuses(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        lane = panel._lanes["stage-a"]
        assert lane.progress.value() == 0
        assert lane.progress.property("stageStatus") == "idle"

        panel.highlight_step(1, "success", 1.2)

        assert lane.progress.value() == 50
        assert lane.progress.toolTip() == "阶段进度：1/2"
        assert lane.progress.property("stageStatus") == "idle"

        panel.highlight_step(2, "running")

        assert lane.progress.value() == 50
        assert lane.progress.property("stageStatus") == "running"

        panel.highlight_step(2, "success", 2.4)

        assert lane.progress.value() == 100
        assert lane.progress.property("stageStatus") == "success"

        panel.reset_all_status()

        assert lane.progress.value() == 0
        assert lane.progress.property("stageStatus") == "idle"
    finally:
        panel.deleteLater()
        assert app is not None


def test_stage_progress_is_smooth_and_jumps_when_hidden(monkeypatch):
    """UI 精修 #9：阶段进度条用 SmoothProgressBar；不可见时直接到终态，value() 始终是逻辑值。"""
    from ui.motion import SmoothProgressBar

    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        lane = panel._lanes["stage-a"]
        assert isinstance(lane.progress, SmoothProgressBar)
        panel.highlight_step(1, "success", 1.0)
        assert lane.progress.value() == 50
        # 面板未显示：不播动画，内部刻度直接到终态
        assert lane.progress.animation.state() != lane.progress.animation.State.Running
        assert lane.progress.text() is not None
    finally:
        panel.deleteLater()
        assert app is not None


def test_step_card_left_bar_transition(monkeypatch):
    """UI 精修 #11：左条换色 200ms 过渡；不可见时跳终态，结束后清空内联样式交还 QSS。"""
    from ui.theme import MOTION_TOKENS

    app = QApplication.instance() or QApplication([])
    step = DummyStep(7, "step-7", "提取", "stage-a", 1)
    card = board_module.StepCard(step, "B1", "无依赖")
    try:
        # 不可见：直接终态，不写内联样式
        card.set_status("running")
        assert card.styleSheet() == ""
        anim = card.left_animation
        assert anim is None or anim.state() != anim.State.Running

        card.show()
        app.processEvents()
        card.set_status("success")
        anim = card.left_animation
        assert anim is not None
        assert anim.duration() == MOTION_TOKENS["base"]
        assert anim.state() == anim.State.Running
        assert "border-left" in card.styleSheet()

        anim.setCurrentTime(anim.duration())
        app.processEvents()
        assert card.styleSheet() == ""
    finally:
        card.close()
        card.deleteLater()
        assert app is not None


def test_step_left_color_matches_qss_priority():
    """t7：左条取色与 QSS 层叠一致：状态色 > 检查点 violet > 选中 blue > 默认 green。"""
    from ui.workbench_board_styles import board_tokens, step_left_color

    c = board_tokens(False)
    assert step_left_color(c, "idle") == c["green"]
    assert step_left_color(c, "idle", selected=True) == c["blue"]
    assert step_left_color(c, "idle", checkpoint=True, selected=True) == c["violet"]
    assert step_left_color(c, "failure", checkpoint=True, selected=True) == c["red"]


def test_selected_idle_card_left_color_is_blue():
    """t7：选中的空闲卡片起止色取 blue，避免换状态时从 green 起跳、回 idle 后再跳色。"""
    app = QApplication.instance() or QApplication([])
    step = DummyStep(8, "step-8", "清洗", "stage-a", 1)
    card = board_module.StepCard(step, "B1", "无依赖")
    try:
        c = board_module.board_tokens(False)
        card.set_selected(True)
        assert card._left_color() == c["blue"]
        card.set_status("running")
        assert card._left_color() == c["blue"]
        card.set_status("idle")
        assert card._left_color() == c["blue"]
        card.set_selected(False)
        assert card._left_color() == c["green"]
    finally:
        card.deleteLater()
        assert app is not None
