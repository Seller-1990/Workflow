# -*- coding: utf-8 -*-
"""Presentation refactors preserve public widget state and module patch seams."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QLabel

from ui import collapsible_section, global_progress, ios_switch, main_window_theme, run_control
from ui import workbench_board
from ui.theme import MOTION_TOKENS, get_colors


@pytest.fixture
def motion_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_switch_reversal_continues_from_displayed_position_and_checks_immediately(motion_app, monkeypatch):
    switch = ios_switch.IosSwitch()
    made = []
    original = ios_switch.make_variant

    def factory(*args):
        made.append(args[0])
        return original(*args)

    monkeypatch.setattr(ios_switch, "make_variant", factory)
    switch.deleteLater()
    switch = ios_switch.IosSwitch()
    try:
        assert made == ["switch"]
        assert switch.sizeHint().width() == 48
        switch.setChecked(True)
        assert switch.isChecked()
        assert switch._pos == 1.0
        assert switch.animation.state() != switch.animation.State.Running
        monkeypatch.setattr(ios_switch, "can_animate", lambda _widget: True)
        switch.setChecked(False)
        switch.animation.setCurrentTime(60)
        current = switch._pos
        switch.setChecked(True)
        assert switch.isChecked()
        assert switch._from == current
        assert switch._to == 1.0
        switch.animation.setCurrentTime(switch.animation.duration())
        assert switch._pos == 1.0
        assert switch.animation.duration() == MOTION_TOKENS["switch"]
        switch.setEnabled(False)
        switch.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
        assert switch.isChecked()
    finally:
        switch.deleteLater()


def test_global_progress_restarts_during_fade_and_keeps_color_callback_seam(motion_app, monkeypatch):
    bar = global_progress.GlobalProgressBar()
    try:
        bar.show_running(4)
        assert bar.height() == bar.VISIBLE_HEIGHT
        assert bar._bar.value() == 0
        bar.set_value(2, 4)
        assert bar._bar.value() == 2
        bar.show_success()
        assert bar._hide_timer.isActive()
        assert bar._bar.value() == 100
        assert bar._chunk_color == get_colors(False)["success"]
        monkeypatch.setattr(global_progress, "can_animate", lambda _widget: True)
        bar._start_fade_out()
        bar._fade_anim.setCurrentTime(60)
        assert bar._opacity.isEnabled()
        assert bar._opacity.opacity() < 1.0
        bar.show_running(3)
        assert not bar._hide_timer.isActive()
        assert bar._fade_anim.state() != bar._fade_anim.State.Running
        assert bar._opacity.opacity() == 1.0
        assert not bar._opacity.isEnabled()
        assert bar._bar.maximum() == 3
        assert bar._bar.value() == 0
        bar._color_anim.setCurrentTime(60)
        current = bar._chunk_color
        bar._set_chunk_color(get_colors(False)["danger"])
        assert bar._color_from == current
        monkeypatch.setattr(global_progress, "mix_hex", lambda *_args: "#123456")
        bar._on_color(0.5)
        assert bar._chunk_color == "#123456"
        bar._color_anim.stop()
        bar._hide()
        assert bar.height() == 0
        assert bar._opacity.opacity() == 1.0
    finally:
        bar._hide_timer.stop()
        bar.deleteLater()


def test_collapsible_section_keeps_requested_and_completed_signal_roles(motion_app, monkeypatch):
    section = collapsible_section.CollapsibleSection("Details")
    requested, completed = [], []
    section.collapse_requested.connect(requested.append)
    section.collapsed_changed.connect(completed.append)
    try:
        section.set_collapsed(True)
        section.set_collapsed(True)
        assert requested == [True]
        assert completed == [True]
        assert section.maximumHeight() == section.collapsed_height
        monkeypatch.setattr(collapsible_section, "can_animate", lambda _widget: True)
        section.set_collapsed(False)
        assert requested == [True, False]
        assert completed == [True]
        section._height_anim.setCurrentTime(section._height_anim.duration())
        assert completed == [True, False]
        assert not section.body.isHidden()
        assert section.maximumHeight() > section.collapsed_height
    finally:
        section.deleteLater()


def test_run_control_factory_lookup_and_callbacks_remain_dynamic(motion_app, monkeypatch):
    labels = []

    class TrackingLabel(QLabel):
        def __init__(self, *args):
            super().__init__(*args)
            labels.append(self)

    monkeypatch.setattr(run_control, "QLabel", TrackingLabel)
    panel = run_control.RunControlPanel()
    calls = []
    try:
        assert panel.lbl_selected in labels
        panel._run = lambda mode: calls.append(mode)
        for attr, *_rest, mode in run_control.RUN_MODE_BUTTONS:
            getattr(panel, attr).click()
            assert calls[-1] == mode
        assert calls == [value[-1] for value in run_control.RUN_MODE_BUTTONS]
        panel.set_running(True)
        assert not panel.btn_run_range.isEnabled()
    finally:
        panel.deleteLater()


def test_card_factory_and_hover_palette_keep_module_monkeypatch_seams(motion_app, monkeypatch):
    labels = []

    class TrackingLabel(QLabel):
        def __init__(self, *args):
            super().__init__(*args)
            labels.append(self)

    monkeypatch.setattr(workbench_board, "QLabel", TrackingLabel)
    card = workbench_board.StepCard(
        SimpleNamespace(id=1, stage_uid="s", name="Step", step_type="python", script_path="s.py"),
        "B1", "No dependencies",
    )
    try:
        assert card.status_badge in labels
        monkeypatch.setattr(main_window_theme, "hover_palette", lambda *_args: ("white", "black", None, None))
        source = main_window_theme.hover_colors_fn(card, {})
        assert source() == ({"background": "white"}, {"background": "black"})
        monkeypatch.setattr(main_window_theme, "hover_palette", lambda *_args: None)
        assert source() is None
    finally:
        card.deleteLater()
