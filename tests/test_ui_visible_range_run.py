# -*- coding: utf-8 -*-
"""The range action must be visible outside the legacy hidden run panel."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from ui.main_window_setup import create_plan_switch
from ui.run_control import RunControlPanel


def _build_visible_plan_switch():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    layout = QVBoxLayout(host)
    panel = RunControlPanel()
    layout.addWidget(panel)
    panel.hide()
    window = SimpleNamespace(run_control=panel)
    switch = create_plan_switch(window)
    layout.addWidget(switch)
    host.show()
    app.processEvents()
    return app, host, window, switch


def test_range_action_is_visible_even_when_legacy_panel_is_hidden():
    app, host, window, switch = _build_visible_plan_switch()
    try:
        button = window.run_control.btn_run_range
        assert not window.run_control.isVisible()
        assert button.parentWidget() is switch
        assert button.isVisible()
        assert button.accessibleName() == "区间运行"
        assert switch.rect().contains(button.geometry())
        calls = []
        window.run_control.run_requested.connect(lambda mode, param: calls.append((mode, param)))

        button.click()

        assert calls == [("step_range", None)]
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()


def test_visible_range_action_reuses_existing_run_lock():
    app, host, window, switch = _build_visible_plan_switch()
    try:
        button = window.run_control.btn_run_range
        calls = []
        window.run_control.run_requested.connect(lambda mode, param: calls.append((mode, param)))
        window.run_control.set_running(True)
        assert button.isVisible()
        assert not button.isEnabled()
        button.click()
        assert calls == []

        window.run_control.set_running(False)
        assert button.isEnabled()
        button.click()
        assert calls == [("step_range", None)]
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()
