# -*- coding: utf-8 -*-
"""Run lifecycle UI state regressions."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from ui import main_window_setup, run_lifecycle_controller


def test_header_run_button_can_return_idle_after_pulse_animation():
    app = QApplication.instance() or QApplication([])
    window = SimpleNamespace(
        _dark_mode=False,
        btn_header_run=QPushButton(),
        lbl_run_state=QLabel(),
    )

    main_window_setup.set_header_run_button_state(window, "running")
    main_window_setup.set_header_run_button_state(window, "idle")

    assert window.btn_header_run.isEnabled() is True
    assert window.lbl_run_state.text() == "● 就绪"
    assert window._pulse_effect.isEnabled() is False
    window.btn_header_run.deleteLater()
    window.lbl_run_state.deleteLater()
    assert app is not None


def test_workflow_finished_unlocks_step_actions_after_pulse_animation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    history_refreshes = []
    monkeypatch.setattr(
        run_lifecycle_controller.QTimer,
        "singleShot",
        lambda _ms, callback: callback(),
    )
    window = SimpleNamespace(
        _dark_mode=False,
        _current_workflow_id=7,
        _running_workflow_id=7,
        _running_workflow_name="wf",
        _stopping_in_progress=False,
        engine=SimpleNamespace(is_running=False),
        btn_header_run=QPushButton(),
        lbl_run_state=QLabel(),
        workflow_config=QWidget(),
        step_table=QWidget(),
        step_editor=QWidget(),
        _bg_running_label=QLabel(),
        run_control=SimpleNamespace(set_running=lambda value: None),
        log_panel=SimpleNamespace(set_running=lambda value: None),
        global_progress=SimpleNamespace(
            show_success=lambda: None,
            show_failure=lambda: None,
        ),
        action_stop_shortcut=SimpleNamespace(setEnabled=lambda value: None),
        statusbar=SimpleNamespace(showMessage=lambda *args: None),
        _apply_run_splitter_profile=lambda profile: None,
        _async_load_history=lambda workflow_id: history_refreshes.append(workflow_id),
    )
    window._refresh_run_lock_panels = lambda: run_lifecycle_controller.refresh_run_lock_panels(window)
    main_window_setup.set_header_run_button_state(window, "running")
    window.step_editor.setEnabled(False)

    run_lifecycle_controller.on_workflow_finished(window, 7, "run-1", "success")

    assert window.step_editor.isEnabled() is True
    assert window.btn_header_run.isEnabled() is True
    assert window.lbl_run_state.text() == "● 就绪"
    assert history_refreshes == [7]
    for widget in (
        window.btn_header_run,
        window.lbl_run_state,
        window.workflow_config,
        window.step_table,
        window.step_editor,
        window._bg_running_label,
    ):
        widget.deleteLater()
    assert app is not None
