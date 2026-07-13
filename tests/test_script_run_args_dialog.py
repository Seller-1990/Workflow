# -*- coding: utf-8 -*-
"""Runtime script argument dialog UI regression tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
)

from ui.script_run_args_dialog import (
    ScriptRunArgsDialog,
    StepArgTarget,
    prompt_run_arg_overrides,
)
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


def test_manual_fallback_collection_stays_unchanged():
    _app()

    manual_target = StepArgTarget(
        uid="manual-step",
        name="手动参数步骤",
        order=1,
        script_path="",
        fixed_args=["--mode", "prod"],
    )
    manual_dialog = ScriptRunArgsDialog([manual_target])
    try:
        manual_edit = manual_dialog.findChild(QLineEdit)
        assert manual_edit is not None
        manual_edit.setText('--year 2026 --region "华东"')
        editor = manual_dialog._editors[0]

        assert editor.collect_temporary_args() == [
            "--year",
            "2026",
            "--region",
            "华东",
        ]
        assert editor.effective_args() == [
            "--mode",
            "prod",
            "--year",
            "2026",
            "--region",
            "华东",
        ]
        assert editor._preview.text() == (
            "最终参数: --mode prod --year 2026 --region '华东'"
        )
    finally:
        manual_dialog.close()
        manual_dialog.deleteLater()


def test_primary_button_describes_running_with_current_parameters():
    _app()
    target = StepArgTarget(
        uid="button-copy",
        name="按钮文案",
        order=1,
        script_path="",
        fixed_args=[],
    )
    dialog = ScriptRunArgsDialog([target])
    try:
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        assert buttons.button(QDialogButtonBox.Ok).text() == "按当前参数运行"
        assert buttons.button(QDialogButtonBox.Cancel).text() == "取消"
    finally:
        dialog.close()
        dialog.deleteLater()


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


def test_prompt_skips_python_script_without_editable_arguments(tmp_path, monkeypatch):
    script_path = tmp_path / "no_args.py"
    script_path.write_text(
        "import argparse\nparser = argparse.ArgumentParser()\n",
        encoding="utf-8",
    )
    target = type(
        "StepStub",
        (),
        {
            "uid": "no-args",
            "name": "无参数脚本",
            "order": 1,
            "step_type": "python",
            "script_path": str(script_path),
            "get_args": lambda self: [],
        },
    )()
    monkeypatch.setattr(
        "ui.script_run_args_dialog.ScriptRunArgsDialog",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("无可填写参数时不应创建弹窗")
        ),
    )

    accepted, overrides = prompt_run_arg_overrides(
        None,
        [target],
        is_python=lambda step: step.step_type == "python",
    )

    assert accepted is True
    assert overrides == {}


def test_argparse_field_collection_stays_unchanged(tmp_path):
    _app()

    script_path = tmp_path / "report_args.py"
    script_path.write_text(
        "\n".join(
            [
                "import argparse",
                "parser = argparse.ArgumentParser()",
                "parser.add_argument('--year', required=True)",
                "parser.add_argument('--region', choices=['华东', '华南'])",
                "parser.add_argument('--verbose', action='store_true')",
            ]
        ),
        encoding="utf-8",
    )
    argparse_target = StepArgTarget(
        uid="argparse-step",
        name="argparse 参数步骤",
        order=2,
        script_path=str(script_path),
        fixed_args=["--mode", "prod"],
    )
    argparse_dialog = ScriptRunArgsDialog([argparse_target])
    try:
        editor = argparse_dialog._editors[0]
        year_edit = editor._form_widgets["year"]
        region_combo = editor._form_widgets["region"]
        verbose_check = editor._form_widgets["verbose"]

        assert isinstance(year_edit, QLineEdit)
        assert isinstance(region_combo, QComboBox)
        assert isinstance(verbose_check, QCheckBox)

        year_edit.setText("2026")
        region_combo.setCurrentText("华东")
        verbose_check.setChecked(True)

        assert editor.collect_temporary_args() == [
            "--year",
            "2026",
            "--region",
            "华东",
            "--verbose",
        ]
        assert editor.effective_args() == [
            "--mode",
            "prod",
            "--year",
            "2026",
            "--region",
            "华东",
            "--verbose",
        ]
        assert editor._preview.text() == (
            "最终参数: --mode prod --year 2026 --region '华东' --verbose"
        )
    finally:
        argparse_dialog.close()
        argparse_dialog.deleteLater()
