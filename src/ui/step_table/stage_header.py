# -*- coding: utf-8 -*-
"""Stage header row renderer for StepTablePanel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QWidget,
)


@dataclass(frozen=True)
class StageHeaderState:
    row: int
    column_count: int
    stage_uid: str
    stage_idx: int
    stage_name: str
    step_count: int
    selected: bool
    can_edit: bool
    is_first: bool
    is_last: bool
    is_collapsed: bool
    colors: dict


@dataclass(frozen=True)
class StageHeaderActions:
    toggle_collapse: Callable[[str], None]
    move_stage_order: Callable[[str, int], None]
    insert_stage_after: Callable[[str], None]
    show_stage_menu: Callable[[str, QPoint], None]


def render_stage_header_row(
    table: QTableWidget,
    style: QStyle,
    state: StageHeaderState,
    actions: StageHeaderActions,
) -> None:
    _clear_stage_row(table, state.row, state.column_count)
    table.setSpan(state.row, 0, 1, state.column_count)
    table.setRowHeight(state.row, 40)

    header_widget = _create_header_widget(style, state, actions)
    item = QTableWidgetItem("")
    item.setFlags(Qt.ItemIsEnabled)
    table.setItem(state.row, 0, item)
    table.setCellWidget(state.row, 0, header_widget)


def _clear_stage_row(table: QTableWidget, row: int, column_count: int) -> None:
    for col in range(column_count):
        table.takeItem(row, col)
        table.setCellWidget(row, col, None)


def _create_header_widget(
    style: QStyle,
    state: StageHeaderState,
    actions: StageHeaderActions,
) -> QWidget:
    header_widget = QWidget()
    header_widget.setObjectName("stageHeader")
    header_widget.setCursor(Qt.PointingHandCursor)
    header_widget.setToolTip("点击整行可选中阶段，新增步骤将默认进入该阶段")
    header_widget.setProperty("selected", bool(state.selected))

    layout = QHBoxLayout(header_widget)
    layout.setContentsMargins(10, 4, 10, 4)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignVCenter)
    layout.addWidget(_create_accent())
    layout.addWidget(_create_collapse_button(state, actions))
    layout.addWidget(_create_title_label(state), stretch=1)
    layout.addStretch()
    layout.addWidget(_create_actions_pill(style, state, actions))
    return header_widget


def _create_accent() -> QFrame:
    accent = QFrame()
    accent.setObjectName("StageHeaderAccent")
    accent.setFixedSize(3, 18)
    return accent


def _create_collapse_button(state: StageHeaderState, actions: StageHeaderActions) -> QToolButton:
    tip = "展开阶段" if state.is_collapsed else "折叠阶段"
    button = QToolButton()
    button.setObjectName("stagePillBtn")
    button.setAutoRaise(True)
    button.setText("▶" if state.is_collapsed else "▼")
    button.setFixedSize(24, 24)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.clicked.connect(lambda _=False: actions.toggle_collapse(state.stage_uid))
    return button


def _create_title_label(state: StageHeaderState) -> QLabel:
    title = QLabel(f"S{state.stage_idx + 1}  {state.stage_name}  ·  {state.step_count} 步")
    title.setObjectName("StageHeaderTitle")
    title.setMinimumWidth(0)
    title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    title.setToolTip(f"S{state.stage_idx + 1} {state.stage_name}\n点击阶段可作为新增步骤的默认归属")
    return title


def _create_actions_pill(
    style: QStyle,
    state: StageHeaderState,
    actions: StageHeaderActions,
) -> QFrame:
    pill = QFrame()
    pill.setObjectName("stagePill")
    layout = QHBoxLayout(pill)
    layout.setContentsMargins(6, 2, 6, 2)
    layout.setSpacing(4)
    layout.addWidget(
        _create_stage_button(
            style,
            QStyle.StandardPixmap.SP_ArrowUp,
            "上移阶段",
            state.can_edit and not state.is_first,
            lambda: actions.move_stage_order(state.stage_uid, -1),
            state.can_edit,
        )
    )
    layout.addWidget(
        _create_stage_button(
            style,
            QStyle.StandardPixmap.SP_ArrowDown,
            "下移阶段",
            state.can_edit and not state.is_last,
            lambda: actions.move_stage_order(state.stage_uid, +1),
            state.can_edit,
        )
    )
    layout.addWidget(
        _create_stage_button(
            style,
            QStyle.StandardPixmap.SP_FileDialogNewFolder,
            "在此阶段后插入新阶段",
            state.can_edit,
            lambda: actions.insert_stage_after(state.stage_uid),
            state.can_edit,
        )
    )
    layout.addWidget(
        _create_stage_button(
            style,
            QStyle.StandardPixmap.SP_TitleBarMenuButton,
            "阶段操作",
            state.can_edit,
            lambda: actions.show_stage_menu(state.stage_uid, pill.mapToGlobal(pill.rect().bottomLeft())),
            state.can_edit,
        )
    )
    return pill


def _create_stage_button(
    style: QStyle,
    icon: QStyle.StandardPixmap,
    tip: str,
    enabled: bool,
    on_click: Callable,
    can_edit: bool,
) -> QToolButton:
    button = QToolButton()
    button.setObjectName("stagePillBtn")
    button.setAutoRaise(True)
    button.setFixedSize(28, 28)
    button.setIconSize(QSize(16, 16))
    button.setIcon(style.standardIcon(icon))
    button.setToolTip(f"{tip}\n（需要先开启编辑）" if (not can_edit and not enabled) else tip)
    button.setAccessibleName(tip)
    button.setEnabled(enabled)
    button.clicked.connect(on_click)
    return button
