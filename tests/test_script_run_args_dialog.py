# -*- coding: utf-8 -*-
"""Runtime script argument dialog UI regression tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QLineEdit,
)

from ui.script_run_args_dialog import (
    ScriptRunArgsDialog,
    StepArgTarget,
    collect_python_step_targets,
    prompt_run_arg_overrides,
)


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert app is not None
    return app


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


def test_saved_runtime_args_prefill_and_explicit_empty_override_can_be_saved():
    _app()
    target = StepArgTarget(
        uid="saved-step",
        name="保存参数步骤",
        order=1,
        script_path="",
        fixed_args=["--mode", "prod"],
        saved_args=["--year", "2026"],
    )
    dialog = ScriptRunArgsDialog([target])
    try:
        editor = dialog._editors[0]
        assert editor._manual_edit is not None
        assert editor.collect_temporary_args() == ["--year", "2026"]
        assert editor.effective_args() == ["--mode", "prod", "--year", "2026"]

        editor._manual_edit.clear()
        editor._save_check.setChecked(True)
        dialog._on_accept()

        assert dialog.overrides() == {"saved-step": []}
        assert dialog.saved_updates() == {"saved-step": []}
    finally:
        dialog.close()
        dialog.deleteLater()


def test_collect_python_step_targets_loads_saved_runtime_args():
    step = type(
        "StepStub",
        (),
        {
            "uid": "saved-target",
            "name": "保存参数",
            "order": 3,
            "step_type": "python",
            "script_path": "job.py",
            "get_args": lambda self: ["--fixed"],
            "get_saved_run_args": lambda self: ["--saved", "1"],
        },
    )()

    targets = collect_python_step_targets([step])

    assert len(targets) == 1
    assert targets[0].fixed_args == ["--fixed"]
    assert targets[0].saved_args == ["--saved", "1"]


def test_saved_runtime_args_prefill_structured_argparse_controls(tmp_path):
    _app()
    script_path = tmp_path / "saved_args.py"
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
    target = StepArgTarget(
        uid="structured-saved",
        name="结构化保存参数",
        order=2,
        script_path=str(script_path),
        fixed_args=[],
        saved_args=[
            "--year",
            "2026",
            "--region=华东",
            "--verbose",
            "--extra",
            "kept",
        ],
    )
    dialog = ScriptRunArgsDialog([target])
    try:
        editor = dialog._editors[0]
        assert editor._manual_edit is None
        assert editor._form_widgets["year"].text() == "2026"
        assert editor._form_widgets["region"].currentText() == "华东"
        assert editor._form_widgets["verbose"].isChecked() is True
        assert editor._extra_edit is not None
        assert editor.collect_temporary_args() == [
            "--year",
            "2026",
            "--region",
            "华东",
            "--verbose",
            "--extra",
            "kept",
        ]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_save_defaults_checkbox_is_disabled_without_edit_mode():
    _app()
    target = StepArgTarget(
        uid="read-only-save",
        name="只读运行参数",
        order=1,
        script_path="",
        fixed_args=[],
        saved_args=["--year", "2026"],
    )
    dialog = ScriptRunArgsDialog([target], allow_save_defaults=False)
    try:
        editor = dialog._editors[0]
        assert editor._save_check.isEnabled() is False
        editor._save_check.setChecked(True)
        assert editor.should_save() is False
    finally:
        dialog.close()
        dialog.deleteLater()


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

    accepted, overrides, saved_updates = prompt_run_arg_overrides(
        None,
        [target],
        is_python=lambda step: step.step_type == "python",
    )

    assert accepted is True
    assert overrides == {}
    assert saved_updates == {}


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
