# -*- coding: utf-8 -*-
"""运行前临时 CLI 参数对话框。"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from script_arg_introspection import ScriptArgument, ScriptArgumentSpec, inspect_script_arguments
from script_arg_utils import (
    CliArgsParseError,
    format_cli_args_for_log,
    merge_step_args,
    parse_cli_args_text,
)
from ui.theme import get_colors


@dataclass
class StepArgTarget:
    uid: str
    name: str
    order: int
    script_path: str
    fixed_args: list[str]


class _StepArgEditor(QGroupBox):
    def __init__(
        self,
        target: StepArgTarget,
        spec: ScriptArgumentSpec,
        parent: QWidget | None = None,
    ) -> None:
        heading_text = f"[{target.order}] {target.name}"
        super().__init__("", parent)
        self.target = target
        self.spec = spec
        self._form_widgets: dict[str, QWidget] = {}
        self._manual_edit: QLineEdit | None = None

        layout = QVBoxLayout(self)
        heading_lbl = QLabel(heading_text)
        heading_lbl.setObjectName("StepArgsHeading")
        heading_lbl.setTextFormat(Qt.PlainText)
        heading_lbl.setWordWrap(True)
        heading_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        heading_font = heading_lbl.font()
        heading_font.setBold(True)
        heading_lbl.setFont(heading_font)
        layout.addWidget(heading_lbl)

        path_lbl = QLabel(target.script_path or "(无脚本路径)")
        path_lbl.setWordWrap(True)
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_lbl)

        fixed_text = format_cli_args_for_log(target.fixed_args)
        layout.addWidget(QLabel(f"固定参数: {fixed_text}"))

        if spec.detected and spec.arguments:
            status = "已识别 argparse 参数"
            if spec.warnings:
                status += f"（警告: {'; '.join(spec.warnings[:2])}）"
            layout.addWidget(QLabel(status))
            form = QFormLayout()
            for arg in spec.arguments:
                widget = self._make_widget(arg)
                key = arg.dest or "/".join(arg.option_strings) or "arg"
                self._form_widgets[key] = widget
                label = self._label_for(arg)
                form.addRow(label, widget)
            layout.addLayout(form)
            self._manual_edit = None
        else:
            reason = "；".join(spec.warnings) if spec.warnings else "未识别到 argparse"
            layout.addWidget(QLabel(f"手动输入临时参数（{reason}）"))
            self._manual_edit = QLineEdit()
            self._manual_edit.setPlaceholderText('--year 2025  或  ["--year", "2025"]')
            layout.addWidget(self._manual_edit)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)
        self._refresh_preview()

        # live preview
        if self._manual_edit is not None:
            self._manual_edit.textChanged.connect(lambda _t: self._refresh_preview())
        for w in self._form_widgets.values():
            if isinstance(w, QLineEdit):
                w.textChanged.connect(lambda _t: self._refresh_preview())
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(lambda _t: self._refresh_preview())
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(lambda _s: self._refresh_preview())

    def _label_for(self, arg: ScriptArgument) -> str:
        names = " / ".join(arg.option_strings) if arg.option_strings else arg.dest
        bits = [names or arg.dest]
        if arg.required:
            bits.append("*必填*")
        if arg.default is not None and arg.action not in {"store_true", "store_false"}:
            bits.append(f"默认={arg.default}")
        if arg.help:
            bits.append(arg.help)
        return " · ".join(str(b) for b in bits if b)

    def _make_widget(self, arg: ScriptArgument) -> QWidget:
        if arg.action in {"store_true", "store_false"}:
            cb = QCheckBox()
            # store_true 默认不勾选；store_false 默认勾选表示“保持默认”
            cb.setChecked(False)
            return cb
        if arg.choices:
            combo = QComboBox()
            combo.setEditable(False)
            combo.addItem("")  # 空=不传，使用默认
            for c in arg.choices:
                combo.addItem(str(c))
            return combo
        edit = QLineEdit()
        if arg.default is not None:
            edit.setPlaceholderText(str(arg.default))
        return edit

    def collect_temporary_args(self) -> list[str]:
        if self._manual_edit is not None:
            return parse_cli_args_text(self._manual_edit.text())

        out: list[str] = []
        for arg in self.spec.arguments:
            key = arg.dest or "/".join(arg.option_strings) or "arg"
            widget = self._form_widgets.get(key)
            if widget is None:
                continue
            flag = None
            if arg.option_strings:
                # prefer long option
                for s in arg.option_strings:
                    if s.startswith("--"):
                        flag = s
                        break
                if flag is None:
                    flag = arg.option_strings[0]
            if arg.action == "store_true":
                if isinstance(widget, QCheckBox) and widget.isChecked():
                    if flag:
                        out.append(flag)
                continue
            if arg.action == "store_false":
                # 勾选表示传 flag 以关闭（常见写法）
                if isinstance(widget, QCheckBox) and widget.isChecked():
                    if flag:
                        out.append(flag)
                continue
            value = ""
            if isinstance(widget, QComboBox):
                value = widget.currentText().strip()
            elif isinstance(widget, QLineEdit):
                value = widget.text().strip()
            if not value:
                if arg.required and not arg.positional:
                    raise CliArgsParseError(f"步骤 [{self.target.order}] {self.target.name}: 参数 {flag or arg.dest} 为必填")
                continue
            if arg.positional:
                out.append(value)
            else:
                if not flag:
                    out.append(value)
                else:
                    out.extend([flag, value])
        return out

    def effective_args(self) -> list[str]:
        return merge_step_args(self.target.fixed_args, self.collect_temporary_args())

    def _refresh_preview(self) -> None:
        try:
            eff = self.effective_args()
            self._preview.setText(f"最终参数: {format_cli_args_for_log(eff)}")
            self._preview.setStyleSheet("")
        except CliArgsParseError as exc:
            self._preview.setText(f"参数错误: {exc}")
            self._preview.setStyleSheet("color: #c0392b;")


class ScriptRunArgsDialog(QDialog):
    """收集本次运行的临时 CLI 参数。"""

    def __init__(
        self,
        targets: Sequence[StepArgTarget],
        *,
        dark: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ScriptRunArgsDialog")
        self.setStyleSheet(_dialog_stylesheet(dark))
        self.setWindowTitle("本次运行参数")
        self.resize(640, 520)
        self._editors: list[_StepArgEditor] = []
        self._result: dict[str, list[str]] = {}

        root_layout = QVBoxLayout(self)
        tip = QLabel(
            "以下参数仅对本次运行生效，不会写回工作流配置。\n"
            "可留空直接运行（保持脚本默认行为）。"
        )
        tip.setWordWrap(True)
        root_layout.addWidget(tip)

        scroll = QScrollArea()
        scroll.setObjectName("ScriptRunArgsScroll")
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("ScriptRunArgsBody")
        body_layout = QVBoxLayout(body)
        for target in targets:
            spec = inspect_script_arguments(target.script_path) if target.script_path else ScriptArgumentSpec(
                script_path="", detected=False, arguments=(), warnings=("无脚本路径",)
            )
            editor = _StepArgEditor(target, spec)
            self._editors.append(editor)
            body_layout.addWidget(editor)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        root_layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("按当前参数运行")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root_layout.addWidget(buttons)

    def _on_accept(self) -> None:
        result: dict[str, list[str]] = {}
        try:
            for editor in self._editors:
                temporary = editor.collect_temporary_args()
                if temporary:
                    result[editor.target.uid] = temporary
        except CliArgsParseError as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        self._result = result
        self.accept()

    def overrides(self) -> dict[str, list[str]]:
        return dict(self._result)


def _dialog_stylesheet(dark: bool) -> str:
    colors = get_colors(dark)
    return f"""
        QDialog#ScriptRunArgsDialog {{
            background-color: {colors["background"]};
            color: {colors["text_primary"]};
        }}
        QDialog#ScriptRunArgsDialog QScrollArea#ScriptRunArgsScroll,
        QDialog#ScriptRunArgsDialog QScrollArea#ScriptRunArgsScroll > QWidget > QWidget,
        QDialog#ScriptRunArgsDialog QWidget#ScriptRunArgsBody {{
            background-color: {colors["background"]};
            border: none;
        }}
        QDialog#ScriptRunArgsDialog QLabel,
        QDialog#ScriptRunArgsDialog QCheckBox {{
            background: transparent;
            color: {colors["text_primary"]};
        }}
        QDialog#ScriptRunArgsDialog QGroupBox {{
            background-color: {colors["surface_secondary"]};
            border: none;
            border-radius: 8px;
        }}
        QDialog#ScriptRunArgsDialog QLineEdit,
        QDialog#ScriptRunArgsDialog QComboBox {{
            background-color: {colors["surface_card"]};
            color: {colors["text_primary"]};
            border: 1px solid {colors["border"]};
            border-radius: 6px;
            padding: 5px 8px;
        }}
        QDialog#ScriptRunArgsDialog QPushButton {{
            background-color: {colors["surface_card"]};
            color: {colors["text_primary"]};
            border: 1px solid {colors["border"]};
            border-radius: 6px;
            padding: 6px 12px;
        }}
        QDialog#ScriptRunArgsDialog QPushButton:hover {{
            background-color: {colors["hover"]};
        }}
    """


def collect_python_step_targets(
    steps: Iterable,
    *,
    is_python: Callable[[object], bool] | None = None,
) -> list[StepArgTarget]:
    """从将运行的步骤中筛出 Python 步骤目标。"""
    def _is_python(step) -> bool:
        if is_python is not None:
            return bool(is_python(step))
        st = getattr(step, "step_type", None) or getattr(step, "type", None)
        return str(st) in {"python", "PYTHON", "Python"}

    targets: list[StepArgTarget] = []
    for step in steps:
        if not _is_python(step):
            continue
        uid = getattr(step, "uid", None)
        if not uid:
            continue
        fixed = []
        if hasattr(step, "get_args"):
            try:
                fixed = list(step.get_args() or [])
            except (TypeError, ValueError):
                fixed = []
        targets.append(
            StepArgTarget(
                uid=str(uid),
                name=str(getattr(step, "name", "") or uid),
                order=int(getattr(step, "order", 0) or 0),
                script_path=str(getattr(step, "script_path", "") or ""),
                fixed_args=fixed,
            )
        )
    return targets


def prompt_run_arg_overrides(
    parent,
    steps: Sequence,
    *,
    dark: bool = False,
    is_python: Callable[[object], bool] | None = None,
) -> tuple[bool, dict[str, list[str]]]:
    """弹出对话框。无 Python 步骤或无可填写参数时直接运行。"""
    targets = collect_python_step_targets(steps, is_python=is_python)
    if not targets:
        return True, {}

    editable_targets = []
    for target in targets:
        if not target.script_path:
            editable_targets.append(target)
            continue
        spec = inspect_script_arguments(target.script_path)
        if spec.arguments or spec.warnings:
            editable_targets.append(target)
    if not editable_targets:
        return True, {}

    dlg = ScriptRunArgsDialog(editable_targets, dark=dark, parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return False, {}
    return True, dlg.overrides()
