# -*- coding: utf-8 -*-
"""StepTablePanel 滚动行为测试。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication

import engine
import ui.step_table.panel as panel_module
from ui.step_table import StepTablePanel


@dataclass
class DummyStage:
    uid: str
    name: str
    order: int


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


def test_step_table_uses_internal_scrollbar_for_many_rows(monkeypatch):
    app = QApplication.instance() or QApplication([])
    stages = [DummyStage(f"stage-{index}", f"阶段 {index}", index) for index in range(1, 9)]
    steps = [
        DummyStep(index, f"step-{index}", f"步骤 {index}", stages[(index - 1) % len(stages)].uid, index)
        for index in range(1, 36)
    ]
    monkeypatch.setattr(panel_module, "get_steps_by_workflow", lambda workflow_id: steps)
    monkeypatch.setattr(panel_module, "get_workflow_uid_name_map", lambda: {})
    monkeypatch.setattr(panel_module, "list_stages", lambda workflow_id: stages)
    monkeypatch.setattr(
        panel_module,
        "get_stage_order_map",
        lambda workflow_id: {stage.uid: stage.order for stage in stages},
    )
    monkeypatch.setattr(panel_module, "get_workflow_by_id", lambda workflow_id: object())
    monkeypatch.setattr(
        engine.WorkflowEngine,
        "compute_batches",
        staticmethod(lambda workflow, workflow_steps, stage_map: [[step] for step in workflow_steps]),
    )

    panel = StepTablePanel()
    try:
        panel.resize(600, 360)
        panel.show()
        panel.load_steps(1)
        app.processEvents()

        table = panel.table

        assert table.rowCount() == len(steps) + len(stages)
        assert table.height() < sum(table.rowHeight(row) for row in range(table.rowCount()))
        assert table.verticalScrollBar().maximum() > 0
        assert table.verticalScrollBar().isVisible()
    finally:
        panel.close()
        panel.deleteLater()
        assert app is not None
