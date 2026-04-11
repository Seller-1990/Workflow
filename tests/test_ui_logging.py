# -*- coding: utf-8 -*-
"""UI 异常日志测试"""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QTableWidgetItem

import ui.run_history as run_history_module
import ui.workflow_config as workflow_config_module
from ui.run_history import RunHistoryPanel
from ui.workflow_config import WorkflowConfigPanel


@dataclass
class MockHistory:
    id: int
    run_id: str = "run-001"
    log_dir: str | None = None
    status: str = "failure"
    start_time: object = None
    duration_seconds: float | None = None


def test_workflow_config_logs_save_failure(monkeypatch, caplog):
    app = QApplication.instance() or QApplication([])
    panel = WorkflowConfigPanel()
    panel._workflow_id = 123
    panel.edit_name.setText("wf")

    monkeypatch.setattr(workflow_config_module, "update_workflow", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(workflow_config_module.QMessageBox, "critical", lambda *args, **kwargs: None)

    with caplog.at_level(logging.ERROR, logger="ui.workflow_config"):
        panel.save_config()

    assert "保存工作流配置失败" in caplog.text
    assert "workflow_id=123" in caplog.text
    assert app is not None


def test_run_history_logs_summary_render_failure(monkeypatch, caplog):
    app = QApplication.instance() or QApplication([])
    panel = RunHistoryPanel()
    history = MockHistory(id=7)

    monkeypatch.setattr(run_history_module, "get_run_histories_by_workflow", lambda workflow_id, limit=20: [history])
    monkeypatch.setattr(run_history_module, "get_step_logs_by_run", lambda history_id: (_ for _ in ()).throw(RuntimeError("boom")))

    with caplog.at_level(logging.DEBUG, logger="ui.run_history"):
        panel.load_history(99)

    assert "加载运行历史统计失败" in caplog.text
    assert "history_id=7" in caplog.text
    assert app is not None


def test_run_history_logs_context_menu_failure_query(monkeypatch, caplog):
    app = QApplication.instance() or QApplication([])
    panel = RunHistoryPanel()
    panel.table.setRowCount(1)
    run_item = QTableWidgetItem("run-001")
    run_item.setData(run_history_module.Qt.UserRole, 9)
    run_item.setData(run_history_module.Qt.UserRole + 1, None)
    run_item.setData(run_history_module.Qt.UserRole + 2, "failure")
    panel.table.setItem(0, 0, run_item)
    panel.table.setItem(0, 1, QTableWidgetItem("失败"))
    panel.table.setItem(0, 2, QTableWidgetItem(""))
    panel.table.setItem(0, 3, QTableWidgetItem(""))

    monkeypatch.setattr(panel.table, "itemAt", lambda pos: run_item)
    monkeypatch.setattr(run_history_module, "get_step_logs_by_run", lambda history_id: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(run_history_module.QMenu, "exec_", lambda self, *_args, **_kwargs: None)

    with caplog.at_level(logging.DEBUG, logger="ui.run_history"):
        panel._show_context_menu(panel.table.viewport().rect().center())

    assert "查询失败步骤状态失败" in caplog.text
    assert "history_id=9" in caplog.text
    assert app is not None
