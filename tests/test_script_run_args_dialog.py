# -*- coding: utf-8 -*-
"""Runtime script argument dialog UI regression tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
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
