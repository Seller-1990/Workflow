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
    # UI 精修 2026-10（方案 B）：运行按钮不再脉动，只有状态圆点呼吸
    assert window.btn_header_run.graphicsEffect() is None
    assert not hasattr(window, "_pulse_effect")
    window.btn_header_run.deleteLater()
    window.lbl_run_state.deleteLater()
    assert app is not None
