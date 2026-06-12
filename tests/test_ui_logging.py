# -*- coding: utf-8 -*-
"""UI 异常日志测试"""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QPushButton, QTableWidgetItem
from PySide6.QtGui import QColor

import ui.run_history as run_history_module
import ui.step_editor as step_editor_module
import ui.workflow_config as workflow_config_module
import ui.main_window as main_window_module
import ui.error_summary as error_summary_module
import database as database_module
from ui.run_history import RunHistoryPanel
from ui.theme import get_menu_stylesheet, get_status_tokens
from ui.log_panel import LogPanel
from ui.main_window import MainWindow
from ui.error_summary import ErrorSummaryDialog
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


def test_log_panel_rerenders_existing_entries_with_current_theme():
    app = QApplication.instance() or QApplication([])
    panel = LogPanel()
    light_error = panel._LEVEL_COLORS["ERROR"].lower()

    panel.append_log("[12:00:00] [ERROR] old failure")
    panel._flush_pending()
    assert light_error in panel._render_entry_html(panel._entries[-1]).lower()

    panel.refresh_theme(True)
    dark_error = panel._LEVEL_COLORS["ERROR"].lower()

    assert dark_error != light_error
    assert dark_error in panel._render_entry_html(panel._entries[-1]).lower()
    assert light_error not in panel._render_entry_html(panel._entries[-1]).lower()
    assert dark_error in panel.log_text.toHtml().lower()
    assert light_error not in panel.log_text.toHtml().lower()
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


def test_main_window_header_run_button_keeps_single_action_after_theme_toggle():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window._toggle_dark_mode(False)
        assert window.btn_header_run.text() == "▶ 运行全流程"
        assert window.btn_header_run.objectName() == "PrimaryAction"
        assert not hasattr(window, "_statusbar_stop_btn")

        window._toggle_dark_mode(True)

        assert window.btn_header_run.text() == "▶ 运行全流程"
        assert window.btn_header_run.objectName() == "PrimaryAction"
        assert not window.action_dark_mode.isVisible()
    finally:
        window.close()
        assert app is not None


def test_header_run_button_stops_when_engine_is_running():
    app = QApplication.instance() or QApplication([])
    window = type("WindowStub", (), {})()
    stop_calls = []
    window.engine = type("EngineStub", (), {"is_running": True})()
    window.btn_header_run = QPushButton("▶ 运行全流程")
    window._stopping_in_progress = False
    window._stop_workflow = lambda: stop_calls.append("stop")

    MainWindow._on_header_run_clicked(window)

    assert stop_calls == ["stop"]
    assert window._stopping_in_progress is True
    assert window.btn_header_run.text() == "■ 正在停止..."
    assert window.btn_header_run.objectName() == "DangerAction"
    assert window.btn_header_run.isEnabled() is False
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


def test_error_summary_open_step_log_emits_connected_handler():
    app = QApplication.instance() or QApplication([])
    dialog = ErrorSummaryDialog(
        [{"step_id": 7, "step_name": "失败步骤", "error_message": "boom"}],
        workflow_id=1,
    )

    try:
        dialog.table.selectRow(0)
        seen = []
        dialog.open_step_log.connect(lambda step_id: seen.append(step_id))

        dialog._open_selected_log()

        assert seen == [7]
    finally:
        dialog.close()
        assert app is not None


def test_error_summary_open_step_log_shows_message_when_log_missing(monkeypatch):
    app = QApplication.instance() or QApplication([])
    dialog = ErrorSummaryDialog(
        [{"step_id": 7, "step_name": "失败步骤", "error_message": "boom"}],
        workflow_id=1,
    )

    try:
        dialog.table.selectRow(0)
        messages = []
        monkeypatch.setattr(error_summary_module, "msg_information", lambda *args: messages.append(args))
        monkeypatch.setattr(database_module, "get_latest_run_history", lambda _workflow_id: None)

        dialog._open_selected_log()

        assert len(messages) == 1
        assert messages[0][2:] == ("提示", "未找到该步骤可打开的日志文件。")
    finally:
        dialog.close()
        assert app is not None
