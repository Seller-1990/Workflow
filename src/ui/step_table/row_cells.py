# -*- coding: utf-8 -*-
"""Step row cell factories for StepTablePanel."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)

from config import StepType
from ui.theme import get_colors, get_type_tokens

logger = logging.getLogger(__name__)


def create_order_item(step, stages: list[dict], stage_idx: int, within_idx: int, batch_idx) -> QTableWidgetItem:
    order_text = f"S{stage_idx + 1}-{within_idx + 1}"
    if batch_idx is not None:
        order_text += f"  B{int(batch_idx) + 1}"

    item = QTableWidgetItem(order_text)
    item.setData(Qt.UserRole, step.id)
    item.setTextAlignment(Qt.AlignCenter)
    stage_name = stage_name_for_step(step, stages)
    batch_tip = f"执行批次 B{int(batch_idx) + 1}" if batch_idx is not None else "执行批次未知"
    item.setToolTip(f"执行阶段 S{stage_idx + 1} {stage_name}\n{batch_tip}")
    return item


def create_type_item(step_type: str, dark: bool) -> QTableWidgetItem:
    item = QTableWidgetItem(StepType.display_name(step_type))
    token = get_type_tokens(dark).get(step_type)
    if token:
        item.setBackground(QColor(token["bg"]))
        item.setForeground(QColor(token["fg"]))
    item.setTextAlignment(Qt.AlignCenter)
    return item


def create_script_item(step, workflow_map) -> QTableWidgetItem:
    script_text = step.script_path or ""
    if step.step_type == "sub_workflow" and workflow_map:
        script_text = workflow_map.get(step.script_path, step.script_path or "")
    item = QTableWidgetItem(script_text)
    item.setToolTip(script_text)
    return item


def create_dependency_item(step, uid_display_map: dict, colors: dict) -> QTableWidgetItem:
    dep_displays, dep_tool_lines = dependency_display_lines(step, uid_display_map)
    dep_text = ", ".join(dep_displays) if dep_displays else ""
    item = QTableWidgetItem(dep_text)
    item.setTextAlignment(Qt.AlignCenter)
    item.setForeground(QColor(colors["primary"]) if dep_text else QColor(colors["text_tertiary"]))
    item.setToolTip("上游依赖：\n" + "\n".join(dep_tool_lines) if dep_tool_lines else "（无显式上游依赖）")
    return item


def create_gate_widget(step, enabled: bool, on_state_changed: Callable[[int], None]) -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    check = QCheckBox()
    check.setChecked(step.is_gate)
    check.setToolTip("检查点：启用后会让本阶段的普通步骤等待它先完成。")
    check.setEnabled(enabled)
    check.stateChanged.connect(on_state_changed)
    layout.addStretch(1)
    layout.addWidget(check)
    layout.addStretch(1)
    return widget


def create_delete_action_widget(
    style: QStyle,
    dark: bool,
    enabled: bool,
    on_delete: Callable,
) -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    button = QToolButton()
    button.setObjectName("tableDangerIcon")
    button.setAutoRaise(True)
    button.setText("")
    button.setFixedSize(32, 32)
    button.setIconSize(QSize(16, 16))
    icon = style.standardIcon(
        getattr(QStyle.StandardPixmap, "SP_TrashIcon", QStyle.StandardPixmap.SP_DialogCloseButton)
    )
    button.setIcon(icon)
    _apply_danger_palette(button, dark)
    button.setToolTip("删除步骤" if enabled else "删除步骤（需要先开启编辑）")
    button.setAccessibleName("删除步骤")
    button.setEnabled(enabled)
    button.clicked.connect(on_delete)

    layout.addStretch(1)
    layout.addWidget(button)
    layout.addStretch(1)
    return widget


def dependency_display_lines(step, uid_display_map: dict) -> tuple[list[str], list[str]]:
    displays = []
    tool_lines = []
    try:
        depends_on = step.get_depends_on() or []
    except Exception as exc:
        logger.warning("读取步骤依赖失败，step_id=%s: %s", getattr(step, "id", None), exc)
        return displays, tool_lines

    for uid in depends_on:
        info = uid_display_map.get(uid)
        if not info:
            continue
        code = info.get("code") or ""
        stage_name = info.get("stage_name") or ""
        display = f"{code}({stage_name})" if (code and stage_name) else code
        if display:
            displays.append(display)
            tool_lines.append(f"{display}  ·  {info.get('step_name') or ''}".rstrip())
    return displays, tool_lines


def stage_name_for_step(step, stages: list[dict]) -> str:
    stage_uid = getattr(step, "stage_uid", None)
    for stage in stages or []:
        if stage.get("uid") == stage_uid:
            return stage.get("name", "")
    return ""


def _apply_danger_palette(button: QToolButton, dark: bool) -> None:
    danger_color = get_colors(dark)["danger"]
    palette = button.palette()
    palette.setColor(QPalette.ButtonText, QColor(danger_color))
    palette.setColor(QPalette.Text, QColor(danger_color))
    button.setPalette(palette)
