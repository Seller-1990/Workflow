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


def test_theme_refresh_recolors_step_card_type_icons(monkeypatch):
    """V9.3 回归：卡片类型图标颜色在创建时烘焙，refresh_theme 必须重设 pixmap。"""
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        card = panel._cards[1]
        assert not card.type_icon_label.pixmap().isNull()
        before = card.type_icon_label.pixmap().toImage()

        panel.refresh_theme(dark=True)

        after = card.type_icon_label.pixmap().toImage()
        assert not after.isNull()
        # 亮暗 token 色不同（python：#4338CA vs #A5ACED），重设后位图必须变化
        assert after != before
    finally:
        panel.deleteLater()
        assert app is not None


def test_gate_card_renders_shield_icon_without_text_pill(monkeypatch):
    """检查点卡片：盾牌图标替代“检查点”文字徽章，TypePill 文字徽章移除，主题切换需重刷图标色。"""
    app = QApplication.instance() or QApplication([])
    step = DummyStep(9, "step-9", "门禁校验", "stage-a", 1, is_gate=True)
    card = board_module.StepCard(step, "B1", "script.py · 检查点")
    try:
        assert card.findChild(QLabel, "TypePill") is None
        assert not card.type_icon_label.pixmap().isNull()
        assert not card.gate_icon_label.pixmap().isNull()
        assert card.type_icon_label.accessibleName() == "类型：Python"
        assert card.gate_icon_label.accessibleName() == "检查点"
        assert "类型：Python" in card.toolTip()

        before = card.gate_icon_label.pixmap().toImage()
        card.refresh_theme(dark=True)
        after = card.gate_icon_label.pixmap().toImage()
        assert not after.isNull()
        # 亮暗 violet token 色不同，重设后位图必须变化
        assert after != before
    finally:
        card.deleteLater()
        assert app is not None


def test_repeated_highlight_does_not_resync_board(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        lane = panel._lanes["stage-a"]
        refresh_calls = []
        sync_calls = []
        original_refresh = lane.refresh_minimum_height

        def counted_refresh():
            refresh_calls.append(1)
            original_refresh()

        monkeypatch.setattr(lane, "refresh_minimum_height", counted_refresh)
        monkeypatch.setattr(panel, "_sync_board_minimum_size", lambda: sync_calls.append(1))

        panel.highlight_step(1, "success", 1.2)
        assert len(refresh_calls) == 1
        assert len(sync_calls) == 1

        panel.highlight_step(1, "success", 1.2)
        assert len(refresh_calls) == 1
        assert len(sync_calls) == 1

        panel.highlight_step(1, "success", 2.4)
        assert len(refresh_calls) == 2
        assert len(sync_calls) == 2
    finally:
        panel.deleteLater()
        assert app is not None


def test_left_right_keys_switch_selected_stage(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        panel.select_stage("stage-b")

        panel.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))

        assert panel.selected_stage_uid() == "stage-c"

        panel.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier))

        assert panel.selected_stage_uid() == "stage-b"
    finally:
        panel.deleteLater()
        assert app is not None


def test_board_minimum_width_tracks_stage_count(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        expected = 3 * STAGE_LANE_MIN_WIDTH + 2 * STAGE_LANE_GAP
        assert panel.board_widget.minimumWidth() == expected
        assert panel.scroll.widgetResizable() is False
    finally:
        panel.deleteLater()
        assert app is not None


def test_selecting_offscreen_stage_moves_horizontal_scrollbar(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        panel.resize(360, 260)
        panel.show()
        app.processEvents()

        panel.select_stage("stage-c")
        app.processEvents()

        hbar = panel.scroll.horizontalScrollBar()
        assert hbar.maximum() > 0
        assert hbar.value() > 0
    finally:
        panel.close()
        panel.deleteLater()
        assert app is not None


def test_stage_lane_height_follows_step_count(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        lane_with_steps = panel._lanes["stage-a"]
        empty_lane = panel._lanes["stage-c"]

        assert empty_lane.minimumHeight() == STAGE_LANE_MIN_HEIGHT
        assert lane_with_steps.sizeHint().height() > empty_lane.sizeHint().height()
    finally:
        panel.deleteLater()
        assert app is not None


def test_multi_step_lane_keeps_step_cards_readable(monkeypatch):
    app = QApplication.instance() or QApplication([])
    stages = [
        DummyStage("stage-a", "准备", 1),
        DummyStage("stage-b", "处理", 2),
        DummyStage("stage-c", "交付", 3),
    ]
    steps = [
        DummyStep(index, f"step-{index}", f"步骤 {index}", "stage-a", index)
        for index in range(1, 9)
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
    try:
        panel.resize(420, 260)
        panel.show()
        panel.load_workflow(100)
        app.processEvents()

        lane = panel._lanes["stage-a"]

        assert lane.minimumHeight() >= lane.sizeHint().height()
        assert lane.height() >= lane.layout.minimumSize().height() + STAGE_LANE_BORDER_HEIGHT
        assert panel.board_widget.minimumHeight() >= lane.minimumHeight()
        assert panel.scroll.verticalScrollBar().maximum() > 0
        for card in lane._cards:
            assert card.height() >= card.sizeHint().height()
    finally:
        panel.close()
        panel.deleteLater()
        assert app is not None


def test_reload_workflow_resyncs_board_height_and_scrollbars(monkeypatch):
    app = QApplication.instance() or QApplication([])
    workflows = {
        100: {
            "stages": [
                DummyStage("stage-a", "准备", 1),
                DummyStage("stage-b", "处理", 2),
                DummyStage("stage-c", "交付", 3),
            ],
            "steps": [
                DummyStep(index, f"step-{index}", f"步骤 {index}", "stage-a", index)
                for index in range(1, 7)
            ],
        },
        200: {
            "stages": [
                DummyStage("stage-a", "准备", 1),
                DummyStage("stage-b", "处理", 2),
                DummyStage("stage-c", "交付", 3),
                DummyStage("stage-d", "校验", 4),
                DummyStage("stage-e", "发布", 5),
            ],
            "steps": [
                DummyStep(index, f"step-{index}", f"步骤 {index}", "stage-b", index)
                for index in range(1, 7)
            ],
        },
    }

    monkeypatch.setattr(
        board_module,
        "list_stages",
        lambda workflow_id: workflows[workflow_id]["stages"],
    )
    monkeypatch.setattr(
        board_module,
        "get_steps_by_workflow",
        lambda workflow_id: workflows[workflow_id]["steps"],
    )
    monkeypatch.setattr(board_module, "get_workflow_by_id", lambda workflow_id: object())
    monkeypatch.setattr(
        board_module,
        "get_stage_order_map",
        lambda workflow_id: {
            stage.uid: stage.order for stage in workflows[workflow_id]["stages"]
        },
    )
    monkeypatch.setattr(
        board_module.WorkflowEngine,
        "compute_batches",
        staticmethod(lambda workflow, workflow_steps, stage_map: [[step] for step in workflow_steps]),
    )

    panel = WorkbenchBoardPanel()
    try:
        panel.resize(420, 260)
        panel.show()
        panel.load_workflow(100)
        app.processEvents()

        panel.load_workflow(200)
        app.processEvents()

        tall_lane = panel._lanes["stage-b"]
        empty_lane = panel._lanes["stage-c"]

        assert tall_lane.minimumHeight() > empty_lane.minimumHeight()
        assert panel.board_widget.minimumHeight() >= tall_lane.minimumHeight()
        assert panel.scroll.horizontalScrollBar().maximum() > 0
        assert panel.scroll.verticalScrollBar().maximum() > 0
    finally:
        panel.close()
        panel.deleteLater()
        assert app is not None


def test_refresh_after_view_shown_restores_board_scroll_area(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        panel.resize(360, 220)
        panel.show()
        app.processEvents()

        panel.board_widget.resize(1, 1)
        panel.refresh_after_view_shown()
        app.processEvents()

        assert panel.board_widget.width() >= panel.board_widget.minimumWidth()
        assert panel.board_widget.height() >= panel.board_widget.minimumHeight()
        assert panel.scroll.horizontalScrollBar().maximum() > 0
    finally:
        panel.close()
        panel.deleteLater()
        assert app is not None
