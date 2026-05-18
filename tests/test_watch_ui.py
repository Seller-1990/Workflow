# -*- coding: utf-8 -*-
"""监听/取消 UI 行为测试

注意：监听启停的按钮（btn_watch_start/btn_watch_stop）与对应的
``MainWindow._sync_watch_controls`` / ``_on_watch_requested`` 已在
UI 重构中移除——监听控制现在通过 ``workflow_config`` 的复选框 +
目录列表持久化到 DB。因此本文件仅保留与取消请求相关的 UI 契约测试。
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QMessageBox

import ui.main_window as main_window_module
from ui.main_window import MainWindow


@dataclass
class MockWorkflow:
    id: int = 1
    name: str = "测试工作流"
    watch_enabled: bool = True
    single_script_enabled: bool = False
    parallel_enabled: bool = False
    folders: list[str] | None = None

    def get_watch_folders(self) -> list[str]:
        return list(self.folders or [])


class DummyPanel:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def recorder(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return recorder


class DummyRunControl:
    def __init__(self):
        self.running = []

    def set_running(self, value: bool):
        self.running.append(bool(value))

    def set_selected_step(self, _step_id: int):
        pass


class DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message: str, *_args):
        self.messages.append(message)


class DummyEngine:
    def __init__(self):
        self.cancel_calls = 0
        self.is_running = False

    def cancel(self):
        self.cancel_calls += 1

    def shutdown(self, wait=False):
        return None


def make_window_stub(engine=None):
    window = type("WindowStub", (), {})()
    window.engine = engine or DummyEngine()
    window.run_control = DummyRunControl()
    window.workflow_config = DummyPanel()
    window.step_table = DummyPanel()
    window.step_editor = DummyPanel()
    window.dag_view = DummyPanel()
    window.run_history = DummyPanel()
    window.log_panel = DummyPanel()
    window.statusbar = DummyStatusBar()
    window._current_workflow_id = None
    window._dark_mode = False
    window._restore_selection_silently = lambda reason: setattr(window, "_restored_reason", reason)
    return window


def test_cancel_request_keeps_running_controls_until_workflow_finished():
    engine = DummyEngine()
    window = make_window_stub(engine=engine)
    window._current_workflow_id = 1

    MainWindow._on_run_requested(window, "cancel", None)

    assert engine.cancel_calls == 1
    assert window.run_control.running == []
    assert [call for call in window.log_panel.calls if call[0] == "set_running"] == []
    assert window.statusbar.messages[-1].startswith("正在停止")


def test_step_finished_propagates_duration_to_dag_view():
    window = make_window_stub()

    MainWindow._on_step_finished(window, 7, "步骤A", "success", 83.0)

    assert ("highlight_step", (7, "success"), {}) in window.step_table.calls
    assert ("update_step_status", (7, "success", 83.0), {}) in window.dag_view.calls


def test_confirm_discard_unsaved_saves_and_blocks_on_step_save_failure(monkeypatch):
    window = make_window_stub()
    save_calls = []
    window.step_editor = SimpleNamespace(
        is_dirty=lambda: True,
        save_step=lambda: save_calls.append(True) or False,
        _is_dirty=True,
    )

    class DummyBox:
        AcceptRole = QMessageBox.AcceptRole
        DestructiveRole = QMessageBox.DestructiveRole
        RejectRole = QMessageBox.RejectRole
        Question = QMessageBox.Question

        def __init__(self, *_args, **_kwargs):
            self._clicked = None
            self._buttons = []

        def setIcon(self, _icon):
            return None

        def setWindowTitle(self, _title):
            return None

        def setText(self, _text):
            return None

        def addButton(self, text, _role):
            button = object()
            self._buttons.append((text, button))
            if text == "保存并切换":
                self._clicked = button
            return button

        def setDefaultButton(self, _button):
            return None

        def exec_(self):
            return None

        def clickedButton(self):
            return self._clicked

    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox", DummyBox)

    result = MainWindow._confirm_discard_unsaved(window, reason="switch_step", new_target=2)

    assert result is False
    assert save_calls == [True]
    assert window._restored_reason == "switch_step"


def test_close_event_blocks_when_step_editor_has_unsaved_changes(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.step_editor._is_dirty = True
        window.step_editor._step_id = 1
        monkeypatch.setattr(window, "_confirm_discard_unsaved", lambda **kwargs: False)

        class DummyEvent:
            def __init__(self):
                self.ignored = False
                self.accepted = False

            def ignore(self):
                self.ignored = True

            def accept(self):
                self.accepted = True

        event = DummyEvent()

        MainWindow.closeEvent(window, event)

        assert event.ignored is True
        assert event.accepted is False
    finally:
        window.close()
        assert app is not None


def test_close_event_waits_for_engine_shutdown_when_running(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    closed_via_event = False
    try:
        calls = []
        window.engine._running = True
        monkeypatch.setattr(window, "_confirm_discard_unsaved", lambda **kwargs: True)
        monkeypatch.setattr(main_window_module, "msg_question", lambda *args, **kwargs: QMessageBox.Yes)
        window.engine.cancel = lambda: calls.append("cancel")
        window.engine.wait_for_completion = lambda timeout=0.0: calls.append(("wait", timeout)) or True
        window.engine.shutdown = lambda wait=False: calls.append(("shutdown", wait))
        window._run_thread = SimpleNamespace(is_alive=lambda: False, join=lambda timeout=None: calls.append(("join", timeout)))

        class DummyEvent:
            def __init__(self):
                self.ignored = False
                self.accepted = False

            def ignore(self):
                self.ignored = True

            def accept(self):
                self.accepted = True

        event = DummyEvent()
        MainWindow.closeEvent(window, event)
        closed_via_event = event.accepted

        assert "cancel" in calls
        assert ("wait", 10.0) in calls
        assert ("shutdown", True) in calls
        assert event.accepted is True
        assert event.ignored is False
    finally:
        window.engine._running = False
        if closed_via_event:
            window.deleteLater()
        else:
            window.close()
        assert app is not None
