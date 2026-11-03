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




def _started_window(progress_totals):
    return SimpleNamespace(
        _current_workflow_id=7,
        _running_workflow_id=None,
        _stopping_in_progress=False,
        engine=SimpleNamespace(is_running=True),
        btn_header_run=QPushButton(),
        lbl_run_state=QLabel(),
        workflow_config=QWidget(),
        step_table=SimpleNamespace(setEnabled=lambda value: None, reset_all_status=lambda: None),
        step_editor=QWidget(),
        _bg_running_label=QLabel(),
        run_control=SimpleNamespace(set_running=lambda value: None),
        log_panel=SimpleNamespace(set_running=lambda value: None),
        global_progress=SimpleNamespace(show_running=progress_totals.append),
        action_stop_shortcut=SimpleNamespace(setEnabled=lambda value: None),
        statusbar=SimpleNamespace(showMessage=lambda *args: None),
        _apply_run_splitter_profile=lambda profile: None,
        _refresh_run_lock_panels=lambda: None,
        main_splitter=SimpleNamespace(sizes=lambda: [100, 100, 300], setSizes=lambda sizes: None),
        workbench_board=SimpleNamespace(reset_all_status=lambda: None),
    )


def test_workflow_started_uses_engine_selected_total(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("database.get_workflow_by_id", lambda workflow_id: SimpleNamespace(name="wf"))
    totals = []
    window = _started_window(totals)

    run_lifecycle_controller.on_workflow_started(window, 7, "run-total", 3)

    assert totals == [3]
    assert not hasattr(window, "_running_step_total")
    window.btn_header_run.deleteLater()
    window.lbl_run_state.deleteLater()
    assert app is not None


def test_workflow_started_legacy_call_keeps_placeholder_progress(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("database.get_workflow_by_id", lambda workflow_id: None)
    totals = []
    window = _started_window(totals)

    run_lifecycle_controller.on_workflow_started(window, 7, "run-legacy")

    assert totals == [1]
    window.btn_header_run.deleteLater()
    window.lbl_run_state.deleteLater()
    assert app is not None
