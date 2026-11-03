# -*- coding: utf-8 -*-
"""Regression boundaries for the four evidenced desktop UI repairs.

Offscreen pixel/layout checks are not native desktop acceptance.
"""

import json
import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QObject, QPoint, QSettings, Qt
from PySide6.QtGui import QColor, QTextDocumentFragment
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QLabel,
    QStyle, QStyleOptionButton, QTabWidget, QVBoxLayout, QWidget,
)

from ui import main_window_setup, panel_controller
from ui.error_summary import ErrorSummaryDialog
from ui.main_window import MainWindow
from ui.run_control import StepRangeDialog
from ui.run_history import RunHistoryPanel
from ui.script_run_args_dialog import ScriptRunArgsDialog, StepArgTarget
from ui.step_table.styles import build_table_stylesheet
from ui.theme import get_app_palette, get_colors, get_stylesheet
from ui.text_utils import plain_text_tooltip
from ui.workbench_board import WorkbenchBoardPanel


@pytest.fixture
def ui_app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    previous_stylesheet, previous_palette = app.styleSheet(), app.palette()
    import ui.run_history as history_module

    settings_file = str(tmp_path / "ui.ini")
    monkeypatch.setattr(
        history_module, "QSettings",
        lambda *_args: QSettings(settings_file, QSettings.IniFormat),
    )
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.setStyleSheet(previous_stylesheet)
    app.setPalette(previous_palette)
    app.processEvents()


def _theme(app, dark):
    app.setPalette(get_app_palette(dark))
    app.setStyleSheet(get_stylesheet(dark))


def _luminance(color):
    values = [color.redF(), color.greenF(), color.blueF()]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(first, second):
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("kind", ["range", "failure"])
def test_local_dialog_root_is_opaque_and_labels_contrast(ui_app, dark, kind):
    _theme(ui_app, dark)
    parent = QWidget()
    parent._dark_mode = dark
    if kind == "range":
        dialog = StepRangeDialog([SimpleNamespace(id=1, name="演示步骤")], parent=parent)
    else:
        dialog = ErrorSummaryDialog([
            {"step_id": 1, "step_name": "演示失败", "error_message": "demo error"},
        ], parent=parent)
    try:
        dialog.show()
        ui_app.processEvents()
        pixel = dialog.grab().toImage().pixelColor(2, 2)
        expected = QColor(get_colors(dark)["background"])
        assert pixel.alpha() == 255
        assert pixel.name() == expected.name(), (pixel.name(), expected.name())
        labels = [label for label in dialog.findChildren(QLabel) if label.text()]
        assert labels
        for label in labels:
            foreground = label.palette().color(label.foregroundRole())
            assert _contrast(foreground, pixel) >= 4.5, label.text()
    finally:
        dialog.close()
        parent.deleteLater()


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("surface", ["ordinary", "table", "arguments"])
def test_checkbox_states_have_visible_edges_and_distinct_checked_fill(ui_app, dark, surface):
    _theme(ui_app, dark)
    if surface == "arguments":
        host = ScriptRunArgsDialog([
            StepArgTarget("demo", "演示", 1, "", []),
        ], dark=dark, allow_save_defaults=False)
        checkbox = host._editors[0]._save_check
    else:
        host = QWidget()
        host.setStyleSheet(
            build_table_stylesheet(get_colors(dark)) if surface == "table" else ""
        )
        checkbox = QCheckBox("本次修改参数")
        QVBoxLayout(host).addWidget(checkbox)
    host.show()
    try:
        images = {}
        for enabled in (True, False):
            checkbox.setEnabled(enabled)
            for checked in (False, True):
                checkbox.setChecked(checked)
                checkbox.clearFocus()
                ui_app.processEvents()
                option = QStyleOptionButton()
                checkbox.initStyleOption(option)
                rect = checkbox.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, checkbox)
                assert rect.width() >= 14 and rect.height() >= 14
                image = checkbox.grab().toImage().copy(rect)
                images[enabled, checked] = image
                center = image.pixelColor(image.width() // 2, image.height() // 2)
                edge = image.pixelColor(0, image.height() // 2)
                if not checked:
                    assert _contrast(edge, center) >= 3.0, (dark, surface, enabled, edge.name(), center.name())
            assert images[enabled, False] != images[enabled, True]
        assert images[True, True] != images[False, True]
    finally:
        host.close()
        host.deleteLater()


def test_range_dialog_accept_cancel_and_selection_are_unchanged(ui_app):
    dialog = StepRangeDialog([
        SimpleNamespace(id=1, name="第一步"), SimpleNamespace(id=2, name="第二步"),
    ], default_start_id=2)
    try:
        assert dialog.selected_range() == (2, 2)
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.Cancel).click()
        assert dialog.result() == QDialog.Rejected
        dialog.cmb_start.setCurrentIndex(0)
        buttons.button(QDialogButtonBox.Ok).click()
        assert dialog.result() == QDialog.Accepted
        assert dialog.selected_range() == (1, 2)
    finally:
        dialog.deleteLater()


def _tooltip_text(widget_or_item):
    tooltip = widget_or_item.toolTip()
    # These fixtures use recognized <b> markup or our explicit <qt> wrapper.
    rich_text = tooltip.startswith("<qt>") or "<b>" in tooltip
    return QTextDocumentFragment.fromHtml(tooltip).toPlainText() if rich_text else tooltip


@pytest.mark.parametrize("text", ["", "普通标题", '<b>字面值</b> &amp; <img src="missing">', '  空格  保留\n\n换行\t制表符  '])
def test_plain_tooltip_helper_keeps_empty_and_literal_semantics(text):
    tooltip = plain_text_tooltip(text)
    if not text:
        assert tooltip == ""
    else:
        fragment = QTextDocumentFragment.fromHtml(tooltip)
        assert fragment.toPlainText() == text
        assert "<img" not in tooltip and "<b>" not in tooltip


@pytest.mark.parametrize("name", ["长工作流名称含<plain>&符号" * 8, '<b>长名称</b> &amp; <img src="missing">\n  多空格  原值' * 8])
def test_workflow_heading_exposes_full_name_and_clears_stale_tooltip(ui_app, name):
    host = QWidget()
    window = SimpleNamespace()
    QVBoxLayout(host).addLayout(main_window_setup.create_title_block(window))
    workflow = SimpleNamespace(name=name, parallel_enabled=False)
    host.resize(180, 140)
    try:
        MainWindow._refresh_workbench_header(window, 1, steps=[], stages=[], workflow=workflow)
        host.show()
        ui_app.processEvents()
        label = window.lbl_workflow_title
        assert label.text() == name
        assert label.textFormat() == Qt.PlainText
        assert _tooltip_text(label) == name
        assert label.width() < label.fontMetrics().horizontalAdvance(name)
        assert host.rect().contains(label.geometry())
        MainWindow._refresh_workbench_header(window, None)
        assert _tooltip_text(label) == label.text() == "请选择工作流"
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("name", ["长阶段名称" * 20, '<b>阶段名</b> &amp; <img src="missing">\n  保留  空格' * 5])
def test_stage_selection_hint_has_full_tooltip_even_at_narrow_width(ui_app, name):
    panel = WorkbenchBoardPanel()
    panel._lanes = {"stage": SimpleNamespace(index=0, stage_name=name, set_selected=lambda _value: None)}
    panel._queue_lane_scroll = lambda *_args: None
    try:
        panel.resize(360, 300)
        panel.select_stage("stage", emit_signal=False)
        assert name in panel.selection_hint.text()
        assert _tooltip_text(panel.selection_hint) == panel.selection_hint.text()
        assert panel.selection_hint.textFormat() == Qt.PlainText
        panel._cards = {7: SimpleNamespace(set_selected=lambda _value: None)}
        panel._step_stage = {7: "stage"}
        panel._queue_step_scroll = lambda *_args: None
        panel.select_step(7, emit_signal=False)
        assert name in panel.selection_hint.text()
        assert _tooltip_text(panel.selection_hint) == panel.selection_hint.text()
        panel.clear()
        assert _tooltip_text(panel.selection_hint) == panel.selection_hint.text()
    finally:
        panel.close()
        panel.deleteLater()


@pytest.mark.parametrize("literal", ["plain_value", '<b>运行</b> &amp; <img src="missing">\n  原值  尾部'])
def test_history_elided_cells_keep_full_values_diagnostics_and_saved_widths(ui_app, literal):
    panel = RunHistoryPanel()
    panel._workflow_id = 1
    panel._settings.setValue(panel._column_widths_key, json.dumps([77, 58, 61, 110]))
    panel._restore_column_widths()
    panel._save_timer.stop()
    record = SimpleNamespace(
        id=1, run_id=f"20261030_full_very_long_run_identifier_{literal}", log_dir="",
        status="cancelled", reason="sub_workflow", notify_status=f"failed: {literal}",
        start_time=datetime(2026, 10, 30, 12, 34, 56), duration_seconds=4000,
    )
    try:
        panel._render_table([record])
        for column in range(panel.table.columnCount()):
            item = panel.table.item(0, column)
            assert item.text() in _tooltip_text(item), (column, item.text(), _tooltip_text(item))
        assert "步骤:" in _tooltip_text(panel.table.item(0, 0))
        assert record.notify_status in _tooltip_text(panel.table.item(0, 1))
        assert [panel.table.columnWidth(i) for i in range(4)] == [77, 58, 61, 110]
        panel._save_timer.stop()
        panel._workflow_id = None
        panel._render_table([])
        assert panel.table.item(0, 0).text() in _tooltip_text(panel.table.item(0, 0))
    finally:
        panel.deleteLater()


def _run_page(app):
    host = QWidget()
    tabs = QTabWidget()
    QVBoxLayout(host).addWidget(tabs)
    window = SimpleNamespace(mode_tabs=tabs, _run_splitter_user_adjusted=False)
    window._on_run_splitter_moved = lambda *args: panel_controller.on_run_splitter_moved(window, *args)
    main_window_setup.add_run_tab(window)
    host.resize(700, 780)
    host.show()
    app.processEvents()
    window.run_history._save_timer.stop()
    window.run_splitter.setSizes([300, 400])
    panel_controller.on_run_splitter_moved(window)
    return host, window


@pytest.mark.parametrize("dark", [False, True])
def test_history_collapse_reclaims_splitter_space_and_restores_manual_sizes(ui_app, dark):
    _theme(ui_app, dark)
    host, window = _run_page(ui_app)
    history = window.run_history
    history.refresh_theme(dark)
    before = window.run_splitter.sizes()
    constraints = history.minimumHeight(), history.maximumHeight()
    settings_before = {key: history._settings.value(key) for key in history._settings.allKeys()}
    try:
        for _ in range(2):
            QTest.mouseClick(history.section.btn_toggle, Qt.LeftButton)
            QTest.qWait(250)
            ui_app.processEvents()
            assert history.section.is_collapsed
            assert not history.section.body.isVisible()
            folded = window.run_splitter.sizes()
            assert folded[0] == history.section.height()
            assert folded[1] > before[1] + 150
            assert window._run_splitter_user_adjusted
            panel_controller.apply_run_splitter_profile(window, "running", force=True)
            panel_controller.ensure_run_log_visible(window)
            ui_app.processEvents()
            assert window.run_splitter.sizes()[0] == history.section.height()
            QTest.mouseClick(history.section.btn_toggle, Qt.LeftButton)
            QTest.qWait(250)
            ui_app.processEvents()
            assert not history.section.is_collapsed
            assert history.section.body.isVisible()
            assert (history.minimumHeight(), history.maximumHeight()) == constraints
            assert all(abs(actual - expected) <= 2 for actual, expected in zip(window.run_splitter.sizes(), before))
            assert window._run_splitter_user_adjusted
        history._save_timer.stop()
        assert history._settings.value(history._column_widths_key) == settings_before.get(
            history._column_widths_key
        )
    finally:
        host.close()
        host.deleteLater()


def test_history_fold_survives_hidden_tab_resize_and_restores_expandability(ui_app):
    host, window = _run_page(ui_app)
    history = window.run_history
    try:
        initial_constraints = history.minimumHeight(), history.maximumHeight()
        window.mode_tabs.addTab(QWidget(), "其他")
        window.mode_tabs.setCurrentIndex(1)
        history.section.set_collapsed(True)
        host.resize(700, 900)
        window.mode_tabs.setCurrentIndex(0)
        ui_app.processEvents()
        assert window.run_splitter.sizes()[0] == history.section.height()
        history.section.set_collapsed(False)
        QTest.qWait(250)
        ui_app.processEvents()
        assert (history.minimumHeight(), history.maximumHeight()) == initial_constraints
        assert window.run_splitter.sizes()[0] >= 180
        assert window.run_splitter.sizes()[1] >= 220
    finally:
        host.close()
        host.deleteLater()


@pytest.mark.parametrize("end_collapsed", [False, True])
def test_history_rapid_reversal_restores_parent_and_only_emits_final_state(ui_app, end_collapsed):
    host, window = _run_page(ui_app)
    history = window.run_history
    section = history.section
    before = window.run_splitter.sizes()
    constraints = history.minimumHeight(), history.maximumHeight()
    requested, completed = [], []
    section.collapse_requested.connect(requested.append)
    section.collapsed_changed.connect(completed.append)
    states = [True, False, True] if end_collapsed else [True, False]
    try:
        for state in states:
            QTest.mouseClick(section.btn_toggle, Qt.LeftButton)
            assert section.is_collapsed is state
            assert section._height_anim.state() == QAbstractAnimation.Running
            section._height_anim.setCurrentTime(60)
            ui_app.processEvents()
            assert (history.minimumHeight(), history.maximumHeight()) == constraints
            assert completed == []
            if state:
                panel_controller.apply_run_splitter_profile(window, "running", force=True)
                panel_controller.ensure_run_log_visible(window)
                assert window.run_splitter.sizes() == before
        QTest.qWait(250)
        ui_app.processEvents()
        assert requested == states
        assert completed == [end_collapsed]
        if end_collapsed:
            assert window.run_splitter.sizes()[0] == section.collapsed_height
            QTest.mouseClick(section.btn_toggle, Qt.LeftButton)
            QTest.qWait(250)
            ui_app.processEvents()
        assert section.body.isVisible()
        assert (history.minimumHeight(), history.maximumHeight()) == constraints
        assert all(abs(actual - expected) <= 2 for actual, expected in zip(window.run_splitter.sizes(), before))
        assert window._run_splitter_user_adjusted
        assert getattr(window, "_run_history_expanded_layout", None) is None
    finally:
        host.close()
        host.deleteLater()


class _DragEvents(QObject):
    def __init__(self, handle):
        super().__init__(handle)
        self.events = []
        handle.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            self.events.append((event.type(), event.buttons()))
        return False


def test_history_fold_cannot_be_reinflated_by_splitter_drag(ui_app):
    host, window = _run_page(ui_app)
    history = window.run_history
    before = window.run_splitter.sizes()
    try:
        QTest.mouseClick(history.section.btn_toggle, Qt.LeftButton)
        QTest.qWait(250)
        ui_app.processEvents()
        handle = window.run_splitter.handle(1)
        observed = _DragEvents(handle)
        for delta in (180, -30):
            center = handle.rect().center()
            QTest.mousePress(handle, Qt.LeftButton, pos=center)
            QTest.mouseMove(handle, center + QPoint(0, delta), delay=10)
            QTest.mouseRelease(handle, Qt.LeftButton, pos=center + QPoint(0, delta))
            ui_app.processEvents()
            assert window.run_splitter.sizes()[0] == history.section.collapsed_height
            assert window.run_splitter.sizes()[1] > before[1] + 150
        assert sum(kind == QEvent.MouseButtonPress for kind, _ in observed.events) == 2
        assert sum(kind == QEvent.MouseButtonRelease for kind, _ in observed.events) == 2
        assert any(kind == QEvent.MouseMove and buttons & Qt.LeftButton for kind, buttons in observed.events)
        QTest.mouseClick(history.section.btn_toggle, Qt.LeftButton)
        QTest.qWait(250)
        ui_app.processEvents()
        assert all(abs(actual - expected) <= 2 for actual, expected in zip(window.run_splitter.sizes(), before))
    finally:
        host.close()
        host.deleteLater()


def test_history_drag_during_collapse_preserves_latest_accepted_manual_layout(ui_app):
    host, window = _run_page(ui_app)
    history = window.run_history
    section = history.section
    before = window.run_splitter.sizes()
    window._run_splitter_user_adjusted = False
    try:
        section.btn_toggle.setFocus()
        QTest.keyClick(section.btn_toggle, Qt.Key_Space)
        assert section.is_collapsed
        assert section._height_anim.state() == QAbstractAnimation.Running
        section._height_anim.pause()
        section._height_anim.setCurrentTime(50)
        handle = window.run_splitter.handle(1)
        observed = _DragEvents(handle)
        moved = []
        window.run_splitter.splitterMoved.connect(lambda *_args: moved.append(window.run_splitter.sizes()))
        center = handle.rect().center()
        QTest.mousePress(handle, Qt.LeftButton, pos=center)
        QTest.mouseMove(handle, center + QPoint(0, 80), delay=10)
        QTest.mouseRelease(handle, Qt.LeftButton, pos=center + QPoint(0, 80))
        ui_app.processEvents()
        accepted = window.run_splitter.sizes()
        assert moved and accepted != before
        assert window._run_splitter_user_adjusted
        assert any(kind == QEvent.MouseMove and buttons & Qt.LeftButton for kind, buttons in observed.events)
        section._height_anim.resume()
        QTest.qWait(250)
        assert window.run_splitter.sizes()[0] == section.collapsed_height
        QTest.mouseClick(section.btn_toggle, Qt.LeftButton)
        QTest.qWait(250)
        ui_app.processEvents()
        assert all(abs(actual - expected) <= 2 for actual, expected in zip(window.run_splitter.sizes(), accepted))
        assert window._run_splitter_user_adjusted
        panel_controller.apply_run_splitter_profile(window, "idle")
        assert window.run_splitter.sizes() == accepted
    finally:
        host.close()
        host.deleteLater()


def test_history_fold_expand_at_narrow_minimum_height_keeps_log_visible(ui_app):
    host, window = _run_page(ui_app)
    history = window.run_history
    constraints = history.minimumHeight(), history.maximumHeight()
    try:
        host.resize(360, 440)
        ui_app.processEvents()
        narrow_size = host.size()
        assert narrow_size.width() < 700
        assert narrow_size.height() < 780
        QTest.mouseClick(history.section.btn_toggle, Qt.LeftButton)
        QTest.qWait(250)
        ui_app.processEvents()
        assert window.run_splitter.sizes()[0] == history.section.collapsed_height
        assert window.log_panel.height() >= 220
        for profile in ("running", "idle"):
            panel_controller.apply_run_splitter_profile(window, profile, force=True)
            panel_controller.ensure_run_log_visible(window)
            assert window.run_splitter.sizes()[0] == history.section.collapsed_height
        QTest.mouseClick(history.section.btn_toggle, Qt.LeftButton)
        QTest.qWait(250)
        ui_app.processEvents()
        assert (history.minimumHeight(), history.maximumHeight()) == constraints
        assert window.run_splitter.sizes()[0] >= 180
        assert window.run_splitter.sizes()[1] >= 220
        assert window.run_splitter.rect().contains(history.geometry())
        assert window.run_splitter.rect().contains(window.log_panel.geometry())
    finally:
        host.close()
        host.deleteLater()
