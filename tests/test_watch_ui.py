# -*- coding: utf-8 -*-
"""监听 UI 行为测试"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication

import ui.main_window as main_window_module
from ui.main_window import MainWindow
from ui.run_control import RunControlPanel


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
        self.available = []
        self.watching = []

    def set_watch_available(self, value: bool):
        self.available.append(bool(value))

    def set_watching(self, value: bool):
        self.watching.append(bool(value))

    def set_selected_step(self, _step_id: int):
        pass


class DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message: str, *_args):
        self.messages.append(message)


class DummyEngine:
    def __init__(self, start_result: bool = True):
        self.start_result = start_result
        self.start_calls = []
        self.stop_calls = 0

    def start_watch(self, workflow):
        self.start_calls.append(workflow)
        return self.start_result

    def stop_watch(self):
        self.stop_calls += 1

    def validate_watch_folders(self, folders):
        return list(folders)


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
    window._sync_watch_controls = lambda workflow: MainWindow._sync_watch_controls(window, workflow)
    return window


def test_workflow_selection_does_not_start_watch(monkeypatch, tmp_path: Path):
    workflow = MockWorkflow(id=42, folders=[str(tmp_path)])
    window = make_window_stub()

    monkeypatch.setattr(main_window_module, "get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 42 else None)

    MainWindow._on_workflow_selected(window, 42)

    assert window.engine.stop_calls == 1
    assert window.engine.start_calls == []
    assert window.run_control.available == [True]
    assert window.run_control.watching == [False]


def test_watch_requests_start_and_stop_explicitly(monkeypatch, tmp_path: Path):
    workflow = MockWorkflow(id=7, folders=[str(tmp_path)])
    engine = DummyEngine(start_result=True)
    window = make_window_stub(engine=engine)
    window._current_workflow_id = 7

    monkeypatch.setattr(main_window_module, "get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 7 else None)

    MainWindow._on_watch_requested(window, True)
    MainWindow._on_watch_requested(window, False)

    assert engine.start_calls == [workflow]
    assert engine.stop_calls == 1
    assert window.run_control.watching == [True, False]


def test_run_control_watch_buttons_follow_watch_state():
    app = QApplication.instance() or QApplication([])
    panel = RunControlPanel()

    panel.set_watch_available(True)
    assert panel.btn_watch_start.isEnabled() is True
    assert panel.btn_watch_stop.isEnabled() is False

    panel.set_watching(True)
    assert panel.btn_watch_start.isEnabled() is False
    assert panel.btn_watch_stop.isEnabled() is True

    panel.set_watching(False)
    assert panel.btn_watch_start.isEnabled() is True
    assert panel.btn_watch_stop.isEnabled() is False

    assert app is not None


def test_sync_watch_controls_disables_invalid_watch_configuration(monkeypatch):
    engine = DummyEngine()
    window = make_window_stub(engine=engine)
    workflow = MockWorkflow(folders=["C:/invalid/missing"])

    def raise_invalid(_folders):
        raise ValueError("bad watch folders")

    engine.validate_watch_folders = raise_invalid

    MainWindow._sync_watch_controls(window, workflow)

    assert window.run_control.available == [False]
