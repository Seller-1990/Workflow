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


def _patch_large_dummy_workflow(monkeypatch, step_count=40):
    stages = [DummyStage("stage-a", "准备", 1), DummyStage("stage-b", "处理", 2)]
    steps = [
        DummyStep(index, f"step-{index}", f"步骤 {index}", "stage-a", index)
        for index in range(1, step_count + 1)
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
    return steps


def test_initial_load_computes_card_geometry_once_per_card(monkeypatch):
    app = QApplication.instance() or QApplication([])
    steps = _patch_large_dummy_workflow(monkeypatch)
    original_refresh = board_module.StepCard.refresh_minimum_height
    card_calls = []

    def counted_card_refresh(card):
        card_calls.append(card.step_id)
        original_refresh(card)

    monkeypatch.setattr(board_module.StepCard, "refresh_minimum_height", counted_card_refresh)
    panel = WorkbenchBoardPanel()
    sync_calls = []
    original_sync = panel._sync_board_minimum_size

    def counted_sync():
        sync_calls.append(1)
        original_sync()

    monkeypatch.setattr(panel, "_sync_board_minimum_size", counted_sync)
    try:
        panel.load_workflow(100)

        assert card_calls == [step.id for step in steps]
        assert len(sync_calls) == 1
        assert panel._ordered_step_ids == [step.id for step in steps]
    finally:
        panel.deleteLater()
        assert app is not None


def test_load_and_clear_do_not_queue_redundant_layout(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _patch_large_dummy_workflow(monkeypatch)
    panel = WorkbenchBoardPanel()
    queued = []
    monkeypatch.setattr(panel, "_queue_board_size_sync", lambda: queued.append(1))
    try:
        panel.load_workflow(100)
        panel.clear()

        assert queued == []
        assert panel.board_widget.minimumSize().isEmpty()
    finally:
        panel.deleteLater()
        assert app is not None


def test_queued_board_layout_coalesces_and_can_run_again(monkeypatch):
    app = QApplication.instance() or QApplication([])
    refreshes = []
    original_refresh = WorkbenchBoardPanel._refresh_board_layout

    def counted_refresh(panel):
        refreshes.append(panel)
        original_refresh(panel)

    monkeypatch.setattr(WorkbenchBoardPanel, "_refresh_board_layout", counted_refresh)
    panel = _panel_with_dummy_workflow(monkeypatch)
    try:
        app.processEvents()
        refreshes.clear()
        for _ in range(20):
            panel._queue_board_size_sync()
        assert refreshes == []
        app.processEvents()
        assert refreshes == [panel]
        assert panel.board_widget.minimumHeight() >= panel._lanes["stage-a"].minimumHeight()

        panel._queue_board_size_sync()
        app.processEvents()
        assert refreshes == [panel, panel]
    finally:
        panel.deleteLater()
        assert app is not None


def test_forty_step_updates_only_refresh_changed_card_and_lane(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _patch_large_dummy_workflow(monkeypatch)
    panel = WorkbenchBoardPanel()
    panel.load_workflow(100)
    try:
        card_calls = {step_id: 0 for step_id in panel._cards}
        for step_id, card in panel._cards.items():
            original_refresh = card.refresh_minimum_height

            def counted_card_refresh(step_id=step_id, original_refresh=original_refresh):
                card_calls[step_id] += 1
                original_refresh()

            monkeypatch.setattr(card, "refresh_minimum_height", counted_card_refresh)

        lane_calls = {stage_uid: 0 for stage_uid in panel._lanes}
        for stage_uid, lane in panel._lanes.items():
            original_refresh = lane.refresh_minimum_height

            def counted_lane_refresh(stage_uid=stage_uid, original_refresh=original_refresh):
                lane_calls[stage_uid] += 1
                original_refresh()

            monkeypatch.setattr(lane, "refresh_minimum_height", counted_lane_refresh)
        sync_calls = []
        original_sync = panel._sync_board_minimum_size

        def counted_sync():
            sync_calls.append(1)
            original_sync()

        monkeypatch.setattr(panel, "_sync_board_minimum_size", counted_sync)

        for step_id in panel._ordered_step_ids:
            panel.highlight_step(step_id, "success", 1.2)

        assert sum(card_calls.values()) == 40
        assert all(count == 1 for count in card_calls.values())
        assert lane_calls == {"stage-a": 40, "stage-b": 0}
        assert len(sync_calls) == 40
        assert panel.board_widget.minimumHeight() >= panel._lanes["stage-a"].minimumHeight()
    finally:
        panel.deleteLater()
        assert app is not None


def test_reset_status_reflows_only_changed_cards_and_restores_board_height(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _patch_large_dummy_workflow(monkeypatch)
    panel = WorkbenchBoardPanel()
    panel.load_workflow(100)
    panel.highlight_step(1, "success", 1.2)
    panel.show()
    app.processEvents()
    try:
        tall_height = panel.board_widget.minimumHeight()
        card_calls = {step_id: 0 for step_id in panel._cards}
        for step_id, card in panel._cards.items():
            original_refresh = card.refresh_minimum_height

            def counted_card_refresh(step_id=step_id, original_refresh=original_refresh):
                card_calls[step_id] += 1
                original_refresh()

            monkeypatch.setattr(card, "refresh_minimum_height", counted_card_refresh)
        unrelated_lane = panel._lanes["stage-b"]
        monkeypatch.setattr(
            unrelated_lane,
            "refresh_minimum_height",
            lambda: (_ for _ in ()).throw(AssertionError("unrelated lane relaid out")),
        )

        panel.reset_all_status()

        assert card_calls == {1: 1, **{step_id: 0 for step_id in range(2, 41)}}
        assert panel.board_widget.minimumHeight() < tall_height
    finally:
        panel.close()
        panel.deleteLater()
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
