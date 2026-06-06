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
from PySide6.QtGui import QColor

import ui.run_history as run_history_module
import ui.step_editor as step_editor_module
import ui.workflow_config as workflow_config_module
import ui.main_window as main_window_module
from ui.run_history import RunHistoryPanel
from ui.theme import get_menu_stylesheet, get_status_tokens, get_colors
from ui.log_panel import LogPanel
from ui.main_window import MainWindow
from ui.step_editor import StepEditorPanel
from ui.workflow_config import WorkflowConfigPanel
from ui.dag_view import NodeCard


@dataclass
class MockHistory:
    id: int
    run_id: str = "run-001"
    log_dir: str | None = None
    status: str = "failure"
    reason: str = "manual"
    start_time: object = None
    duration_seconds: float | None = None


def test_workflow_config_logs_save_failure(monkeypatch, caplog):
    app = QApplication.instance() or QApplication([])
    panel = WorkflowConfigPanel()
    panel._workflow_id = 123
    panel.edit_name.setText("wf")

    monkeypatch.setattr(workflow_config_module, "update_workflow", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(workflow_config_module, "msg_critical", lambda *args, **kwargs: None)

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
    monkeypatch.setattr(run_history_module, "get_step_log_summary_by_runs", lambda history_ids: (_ for _ in ()).throw(RuntimeError("boom")))

    with caplog.at_level(logging.DEBUG, logger="ui.run_history"):
        panel.load_history(99)

    assert "加载运行历史统计失败" in caplog.text
    assert "workflow_id=99" in caplog.text
    assert app is not None


def test_step_editor_logs_dependency_preview_failure(monkeypatch, caplog):
    app = QApplication.instance() or QApplication([])
    panel = StepEditorPanel()
    try:
        panel._step_id = 123
        monkeypatch.setattr(
            step_editor_module,
            "get_session",
            lambda: (_ for _ in ()).throw(RuntimeError("db down")),
        )

        with caplog.at_level(logging.WARNING, logger="ui.step_editor"):
            panel._do_refresh_dependency_preview()

        assert "刷新依赖预览失败" in caplog.text
        assert "step_id=123" in caplog.text
        assert "依赖预览刷新失败" in panel.dep_warning.text()
    finally:
        panel.deleteLater()
        assert app is not None


def test_step_editor_logs_control_state_update_failure(caplog):
    app = QApplication.instance() or QApplication([])
    panel = StepEditorPanel()
    try:
        with caplog.at_level(logging.WARNING, logger="ui.step_editor"):
            panel._safe_update_control_state(
                "测试控件",
                lambda: (_ for _ in ()).throw(RuntimeError("widget down")),
            )

        assert "更新步骤编辑器控件状态失败: 测试控件" in caplog.text
    finally:
        panel.deleteLater()
        assert app is not None


def test_run_history_context_menu_uses_cached_failure_summary(monkeypatch):
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
    panel._history_step_summary = {9: {"failure": 1}}

    captured = {}

    class DummySignal:
        def connect(self, _callback):
            return None

    class DummyAction:
        def __init__(self, text: str):
            self._text = text
            self._enabled = True
            self.triggered = DummySignal()

        def text(self):
            return self._text

        def setEnabled(self, enabled: bool):
            self._enabled = bool(enabled)

        def isEnabled(self):
            return self._enabled

    class DummyMenu:
        def __init__(self, *_args, **_kwargs):
            self._actions = []
            self._style = ""

        def addAction(self, text: str):
            action = DummyAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def setStyleSheet(self, style: str):
            self._style = style

        def exec(self, *_args, **_kwargs):
            captured["style"] = self._style
            captured["actions"] = {
                action.text(): action.isEnabled()
                for action in self._actions
            }

    monkeypatch.setattr(panel.table, "itemAt", lambda pos: run_item)
    monkeypatch.setattr(run_history_module, "QMenu", DummyMenu)

    panel._show_context_menu(panel.table.viewport().rect().center())

    assert captured["actions"]["查看失败步骤"] is True
    assert captured["style"] == get_menu_stylesheet(False)
    assert app is not None


def test_log_panel_level_menu_tracks_theme_stylesheet():
    app = QApplication.instance() or QApplication([])
    panel = LogPanel()

    assert panel._level_menu.styleSheet() == get_menu_stylesheet(False)

    panel.refresh_theme(True)

    assert panel._level_menu.styleSheet() == get_menu_stylesheet(True)
    assert app is not None


def test_main_window_save_current_does_not_report_success_when_step_save_fails():
    window = type("WindowStub", (), {})()
    calls = []
    window.workflow_config = type("WorkflowConfigStub", (), {
        "save_config": lambda self: calls.append("config") or True
    })()
    window.step_editor = type("StepEditorStub", (), {
        "_step_id": 1,
        "is_dirty": lambda self: False,
        "save_step": lambda self: calls.append("step") or False
    })()
    messages = []
    window.statusbar = type("StatusBarStub", (), {
        "showMessage": lambda self, message, *_args: messages.append(message)
    })()

    MainWindow._save_current(window)

    assert calls == ["config", "step"]
    assert messages == ["保存未完成，请检查输入后重试"]


def test_ctrl_s_shortcut_uses_unified_save_action():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        assert window.action_save_shortcut.shortcut().toString() == "Ctrl+S"
        window._edit_mode = True

        messages = []
        window.statusbar.showMessage = lambda message, *_args: messages.append(message)
        window.workflow_config.save_config = lambda: messages.append("config") or True
        window.step_editor._step_id = 1
        window.step_editor.save_step = lambda: messages.append("step") or True

        window.action_save_shortcut.trigger()

        assert messages == ["config", "step", "已保存"]
    finally:
        window.close()
        assert app is not None


def test_run_history_uses_theme_status_tokens_for_row_colors():
    app = QApplication.instance() or QApplication([])
    panel = RunHistoryPanel()
    history = MockHistory(id=3, status="failure", duration_seconds=12)
    panel._history_step_summary = {3: {"failure": 1}}

    panel._render_table([history])

    status_tokens = get_status_tokens(False)["failure"]
    assert panel.table.item(0, 0).background().color().name().lower() == QColor(status_tokens["bg"]).name().lower()
    assert panel.table.item(0, 1).foreground().color().name().lower() == QColor(status_tokens["fg"]).name().lower()
    assert app is not None


def test_main_window_statusbar_stop_button_stays_light_when_theme_toggle_called():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._toggle_dark_mode(False)
        light_style = window._statusbar_stop_btn.styleSheet()
        assert get_colors(False)["danger"] in light_style

        window._toggle_dark_mode(True)

        forced_light_style = window._statusbar_stop_btn.styleSheet()
        assert get_colors(False)["danger"] in forced_light_style
        assert forced_light_style == light_style
        assert not window.action_dark_mode.isVisible()
    finally:
        window.close()
        assert app is not None


def test_node_card_shows_duration_badge_and_hides_it_when_empty():
    app = QApplication.instance() or QApplication([])
    card = NodeCard(
        step_id=1,
        title="1. 测试步骤",
        step_type="python",
        type_color="#1E40AF",
        is_gate=True,
    )
    try:
        assert card.duration_badge.isHidden() is True

        card.set_duration_seconds(83)

        assert card.duration_badge.isHidden() is False
        assert card.duration_badge.text() == "1m23s"
        assert "检查点" in card.type_label.text()

        card.set_duration_seconds(None)

        assert card.duration_badge.isHidden() is True
    finally:
        card.deleteLater()
        assert app is not None
