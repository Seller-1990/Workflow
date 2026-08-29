# -*- coding: utf-8 -*-
"""运行前临时 CLI 参数对话框。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

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
from ui.theme import get_colors, msg_warning


@dataclass
class StepArgTarget:
    uid: str
    name: str
    order: int
    script_path: str
    fixed_args: list[str]
    saved_args: list[str] = field(default_factory=list)


class _StepArgEditor(QGroupBox):
    def __init__(
        self,
        target: StepArgTarget,
        spec: ScriptArgumentSpec,
        *,
        allow_save_defaults: bool = True,
        parent: QWidget | None = None,
        dark: bool = False,
    ) -> None:
        heading_text = f"[{target.order}] {target.name}"
        super().__init__("", parent)
        self.target = target
        self.spec = spec
        self._dark = dark
        self._form_widgets: dict[str, QWidget] = {}
        self._manual_edit: QLineEdit | None = None
        self._extra_edit: QLineEdit | None = None

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
            remaining = self._prefill_form_widgets(target.saved_args)
            if remaining:
                self._extra_edit = QLineEdit()
                self._extra_edit.setText(json.dumps(remaining, ensure_ascii=False))
                self._extra_edit.setPlaceholderText('["--extra", "value"]')
                form.addRow("未识别的保存参数", self._extra_edit)
            layout.addLayout(form)
            self._manual_edit = None
        else:
            reason = "；".join(spec.warnings) if spec.warnings else "未识别到 argparse"
            layout.addWidget(QLabel(f"手动输入临时参数（{reason}）"))
            self._manual_edit = QLineEdit()
            if target.saved_args:
                self._manual_edit.setText(json.dumps(target.saved_args, ensure_ascii=False))
            self._manual_edit.setPlaceholderText('--year 2025  或  ["--year", "2025"]')
            layout.addWidget(self._manual_edit)

        self._save_check = QCheckBox("将本次参数保存到步骤")
        self._save_check.setObjectName("SaveRunArgsCheck")
        self._save_check.setEnabled(allow_save_defaults)
        if not allow_save_defaults:
            self._save_check.setToolTip("开启编辑模式后可保存运行参数")
        layout.addWidget(self._save_check)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)
        self._refresh_preview()

        # live preview
        if self._manual_edit is not None:
            self._manual_edit.textChanged.connect(lambda _t: self._refresh_preview())
        if self._extra_edit is not None:
            self._extra_edit.textChanged.connect(lambda _t: self._refresh_preview())
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

    def _prefill_form_widgets(self, saved_args: Sequence[str]) -> list[str]:
        remaining = [True] * len(saved_args)
        option_map = {
            option: arg
            for arg in self.spec.arguments
            if not arg.positional
            for option in arg.option_strings
        }
        for index, token in enumerate(saved_args):
            if not remaining[index]:
                continue
            option = token
            inline_value = None
            if token.startswith("-") and "=" in token:
                option, inline_value = token.split("=", 1)
            arg = option_map.get(option)
            if arg is None:
                continue
            widget = self._form_widgets.get(self._key_for(arg))
            if widget is None:
                continue
            if arg.action in {"store_true", "store_false"}:
                if isinstance(widget, QCheckBox):
                    widget.setChecked(True)
                    remaining[index] = False
                continue
            if arg.nargs not in {None, 1, "?"}:
                continue
            value_index = None
            value = inline_value
            if value is None and index + 1 < len(saved_args):
                value_index = index + 1
                value = saved_args[value_index]
            if value is None or not self._set_widget_value(widget, value):
                continue
            remaining[index] = False
            if value_index is not None:
                remaining[value_index] = False

        unknown_option_values = {
            index + 1
            for index, token in enumerate(saved_args[:-1])
            if remaining[index] and token.startswith("-") and remaining[index + 1]
        }
        positional_values = [
            index
            for index, token in enumerate(saved_args)
            if (
                remaining[index]
                and index not in unknown_option_values
                and not token.startswith("-")
            )
        ]
        for arg in (item for item in self.spec.arguments if item.positional):
            if arg.nargs not in {None, 1, "?"} or not positional_values:
                continue
            value_index = positional_values.pop(0)
            widget = self._form_widgets.get(self._key_for(arg))
            if widget is not None and self._set_widget_value(widget, saved_args[value_index]):
                remaining[value_index] = False
        return [token for index, token in enumerate(saved_args) if remaining[index]]

    @staticmethod
    def _key_for(arg: ScriptArgument) -> str:
        return arg.dest or "/".join(arg.option_strings) or "arg"

    @staticmethod
    def _set_widget_value(widget: QWidget, value: str) -> bool:
        if isinstance(widget, QComboBox):
            index = widget.findText(value)
            if index < 0:
                return False
            widget.setCurrentIndex(index)
            return True
        if isinstance(widget, QLineEdit):
            widget.setText(value)
            return True
        return False

    def collect_temporary_args(self) -> list[str]:
        if self._manual_edit is not None:
            return parse_cli_args_text(self._manual_edit.text())

        out: list[str] = []
        for arg in self.spec.arguments:
            key = self._key_for(arg)
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
        if self._extra_edit is not None:
            out.extend(parse_cli_args_text(self._extra_edit.text()))
        return out

    def effective_args(self) -> list[str]:
        return merge_step_args(self.target.fixed_args, self.collect_temporary_args())

    def should_save(self) -> bool:
        return self._save_check.isEnabled() and self._save_check.isChecked()

    def _refresh_preview(self) -> None:
        try:
            eff = self.effective_args()
            self._preview.setText(f"最终参数: {format_cli_args_for_log(eff)}")
            self._preview.setStyleSheet("")
        except CliArgsParseError as exc:
            self._preview.setText(f"参数错误: {exc}")
            self._preview.setStyleSheet(f"color: {get_colors(self._dark)['danger_aa']};")


class ScriptRunArgsDialog(QDialog):
    """收集本次运行的临时 CLI 参数。"""

    def __init__(
        self,
        targets: Sequence[StepArgTarget],
        *,
        dark: bool = False,
        allow_save_defaults: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ScriptRunArgsDialog")
        self._dark = bool(dark)
        self.setStyleSheet(_dialog_stylesheet(dark))
        self.setWindowTitle("本次运行参数")
        self.resize(640, 520)
        self._editors: list[_StepArgEditor] = []
        self._result: dict[str, list[str]] = {}
        self._saved_updates: dict[str, list[str]] = {}

        root_layout = QVBoxLayout(self)
        tip_text = "参数默认从步骤保存值加载；清空后运行可临时忽略保存值。"
        if allow_save_defaults:
            tip_text += "\n只有勾选“将本次参数保存到步骤”才会写回配置。"
        else:
            tip_text += "\n当前未开启编辑模式，本次只能临时覆盖。"
        tip = QLabel(tip_text)
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
            editor = _StepArgEditor(
                target,
                spec,
                allow_save_defaults=allow_save_defaults,
                dark=self._dark,
            )
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
        saved_updates: dict[str, list[str]] = {}
        try:
            for editor in self._editors:
                temporary = editor.collect_temporary_args()
                result[editor.target.uid] = temporary
                if editor.should_save():
                    saved_updates[editor.target.uid] = list(temporary)
        except CliArgsParseError as exc:
            msg_warning(self, self._dark, "参数错误", str(exc))
            return
        self._result = result
        self._saved_updates = saved_updates
        self.accept()

    def overrides(self) -> dict[str, list[str]]:
        return dict(self._result)

    def saved_updates(self) -> dict[str, list[str]]:
        return dict(self._saved_updates)


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
        saved = []
        if hasattr(step, "get_saved_run_args"):
            try:
                value = step.get_saved_run_args()
                if isinstance(value, list) and all(isinstance(arg, str) for arg in value):
                    saved = list(value)
            except (TypeError, ValueError):
                saved = []
        targets.append(
            StepArgTarget(
                uid=str(uid),
                name=str(getattr(step, "name", "") or uid),
                order=int(getattr(step, "order", 0) or 0),
                script_path=str(getattr(step, "script_path", "") or ""),
                fixed_args=fixed,
                saved_args=saved,
            )
        )
    return targets


def prompt_run_arg_overrides(
    parent,
    steps: Sequence,
    *,
    dark: bool = False,
    is_python: Callable[[object], bool] | None = None,
    allow_save_defaults: bool = True,
) -> tuple[bool, dict[str, list[str]], dict[str, list[str]]]:
    """弹出对话框。无 Python 步骤或无可填写参数时直接运行。"""
    targets = collect_python_step_targets(steps, is_python=is_python)
    if not targets:
        return True, {}, {}

    editable_targets = []
    for target in targets:
        if not target.script_path:
            editable_targets.append(target)
            continue
        spec = inspect_script_arguments(target.script_path)
        if target.saved_args or spec.arguments or spec.warnings:
            editable_targets.append(target)
    if not editable_targets:
        return True, {}, {}

    dlg = ScriptRunArgsDialog(
        editable_targets,
        dark=dark,
        allow_save_defaults=allow_save_defaults,
        parent=parent,
    )
    if dlg.exec() != QDialog.Accepted:
        return False, {}, {}
    return True, dlg.overrides(), dlg.saved_updates()
