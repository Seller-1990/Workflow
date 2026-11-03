# -*- coding: utf-8 -*-
"""Presentation, geometry and theme regression tests for the run-args dialog."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QLabel,
    QScrollArea,
)

from ui.script_run_args_dialog import ScriptRunArgsDialog, StepArgTarget
from ui.theme import get_stylesheet


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    return app


def test_long_chinese_step_name_is_wrapped_content_not_groupbox_title():
    app = _app()
    old_stylesheet = app.styleSheet()
    app.setStyleSheet(get_stylesheet(False))
    long_name = "按地区与渠道汇总销售明细并生成中文经营分析报告" * 3
    target = StepArgTarget(
        uid="step-long-name",
        name=long_name,
        order=12,
        script_path="",
        fixed_args=["--mode", "prod"],
    )
    dialog = ScriptRunArgsDialog([target])

    try:
        dialog.show()
        app.processEvents()

        groups = dialog.findChildren(QGroupBox)
        assert len(groups) == 1
        group = groups[0]
        heading_text = f"[{target.order}] {target.name}"

        assert group.title() == ""
        headings = [
            label
            for label in group.findChildren(QLabel)
            if label.text() == heading_text
        ]
        assert len(headings) == 1
        heading = headings[0]
        path_label = next(
            label
            for label in group.findChildren(QLabel)
            if label.text() == "(无脚本路径)"
        )

        assert heading.textFormat() == Qt.PlainText
        assert heading.wordWrap()
        assert bool(heading.textInteractionFlags() & Qt.TextSelectableByMouse)
        assert heading.height() > heading.fontMetrics().lineSpacing()
        assert not heading.geometry().intersects(path_label.geometry())
        assert path_label.geometry().top() > heading.geometry().bottom()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.setStyleSheet(old_stylesheet)


def test_light_dialog_overrides_a_stale_dark_application_palette():
    app = _app()
    old_palette = app.palette()
    old_stylesheet = app.styleSheet()
    dark_palette = QPalette(old_palette)
    dark_palette.setColor(QPalette.Window, QColor("#101010"))
    dark_palette.setColor(QPalette.Base, QColor("#101010"))
    app.setStyleSheet("")
    app.setPalette(dark_palette)
    target = StepArgTarget(
        uid="light-theme",
        name="浅色主题",
        order=1,
        script_path="",
        fixed_args=[],
    )
    dialog = ScriptRunArgsDialog([target], dark=False)
    try:
        dialog.show()
        app.processEvents()
        scroll = dialog.findChild(QScrollArea)
        assert scroll is not None
        dialog_pixel = dialog.grab().toImage().pixelColor(8, 40)
        viewport_image = scroll.viewport().grab().toImage()
        viewport_pixel = viewport_image.pixelColor(
            8,
            max(8, viewport_image.height() - 8),
        )

        assert dialog_pixel.lightness() > 220
        assert viewport_pixel.lightness() > 220
    finally:
        dialog.close()
        dialog.deleteLater()
        app.setPalette(old_palette)
        app.setStyleSheet(old_stylesheet)


@pytest.mark.parametrize("width", [640, 420])
def test_long_heading_wraps_without_scroll_escape_at_constrained_width(width):
    app = _app()
    old_stylesheet = app.styleSheet()
    app.setStyleSheet(get_stylesheet(False))
    target = StepArgTarget(
        uid="constrained-long-name",
        name="按地区与渠道汇总销售明细并生成中文经营分析报告" * 3,
        order=12,
        script_path="",
        fixed_args=["--mode", "prod"],
    )
    dialog = ScriptRunArgsDialog([target])
    try:
        dialog.setFixedWidth(width)
        dialog.show()
        app.processEvents()
        group = dialog.findChild(QGroupBox)
        assert group is not None
        heading = group.findChild(QLabel, "StepArgsHeading")
        assert heading is not None
        path_label = next(label for label in group.findChildren(QLabel) if label.text() == "(无脚本路径)")
        scroll = dialog.findChild(QScrollArea)
        assert scroll is not None

        assert dialog.width() == width
        assert 0 < heading.width() < scroll.viewport().width() < width
        metrics = heading.fontMetrics()
        assert metrics.horizontalAdvance("中文") > 0
        assert metrics.horizontalAdvance(heading.text()) > heading.width()
        assert heading.height() > metrics.lineSpacing()
        assert heading.height() >= heading.heightForWidth(heading.width())
        assert not heading.geometry().intersects(path_label.geometry())
        assert path_label.geometry().top() > heading.geometry().bottom()
        assert heading.textFormat() == Qt.PlainText
        assert heading.wordWrap()
        assert bool(heading.textInteractionFlags() & Qt.TextSelectableByMouse)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.widget().width() <= scroll.viewport().width()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.setStyleSheet(old_stylesheet)
