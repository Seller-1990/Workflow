# -*- coding: utf-8 -*-
"""Reusable StepEditorPanel section builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.collapsible_section import CollapsibleSection


@dataclass
class DependencySummarySection:
    section: CollapsibleSection
    warning: QLabel
    depends_on_list: QListWidget
    dependents_list: QListWidget
    lists_container: QWidget
    hint: QLabel


@dataclass
class AdvancedSettingsSection:
    section: CollapsibleSection
    cwd_row: QWidget
    cwd_label: QLabel
    cwd_edit: QLineEdit
    browse_cwd_button: QPushButton
    sub_workflow_filter: QWidget
    target_search_edit: QLineEdit
    target_scope_combo: QComboBox
    args_edit: QLineEdit
    saved_run_args_edit: QLineEdit
    output_paths_edit: QLineEdit
    theme_edit: QLineEdit
    timeout_spin: QSpinBox
    retry_spin: QSpinBox
    skip_on_success_check: QCheckBox
    dependency_list: QListWidget


@dataclass
class AdvancedSettingsControls:
    cwd_row: QWidget
    cwd_label: QLabel
    cwd_edit: QLineEdit
    browse_cwd_button: QPushButton
    sub_workflow_filter: QWidget
    target_search_edit: QLineEdit
    target_scope_combo: QComboBox
    args_edit: QLineEdit
    saved_run_args_edit: QLineEdit
    output_paths_edit: QLineEdit
    theme_edit: QLineEdit
    timeout_spin: QSpinBox
    retry_spin: QSpinBox
    skip_on_success_check: QCheckBox
    dependency_list: QListWidget


def create_dependency_summary_section(colors: dict, navigate_from_item: Callable) -> DependencySummarySection:
    section = CollapsibleSection("依赖摘要（只读）", collapsed=True)
    layout = section.body_layout

    warning = QLabel("")
    warning.setVisible(False)
    warning.setWordWrap(True)
    warning.setStyleSheet(f"color:{colors['warning']}; font-size:11px;")
    layout.addWidget(warning)

    lists_container = QWidget()
    lists_layout = QHBoxLayout(lists_container)
    lists_layout.setContentsMargins(0, 0, 0, 0)
    lists_layout.setSpacing(12)

    depends_on_list = _create_dependency_list("我的上游依赖", lists_layout, navigate_from_item)
    dependents_list = _create_dependency_list("依赖此步骤的步骤", lists_layout, navigate_from_item)

    lists_container.setStyleSheet(
        f"""
        QLabel {{ color:{colors['text_secondary']}; font-size:11px; font-weight:600; }}
        QListWidget {{
            background: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 8px;
        }}
        QListWidget::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {colors['border']};
            border-radius: 4px;
            background: {colors['surface']};
        }}
        QListWidget::indicator:checked {{
            background: {colors['primary']};
            border: 1px solid {colors['primary']};
        }}
        QListWidget::item {{ padding: 6px 8px; }}
        QListWidget::item:selected {{ background: {colors['selected_bg']}; }}
        """
    )
    layout.addWidget(lists_container)

    hint = QLabel("提示：双击条目可定位到对应步骤（列表选中 + 打开编辑器）。")
    hint.setStyleSheet(f"color:{colors['text_tertiary']}; font-size:11px;")
    layout.addWidget(hint)

    section.setVisible(False)
    return DependencySummarySection(
        section=section,
        warning=warning,
        depends_on_list=depends_on_list,
        dependents_list=dependents_list,
        lists_container=lists_container,
        hint=hint,
    )


def create_advanced_settings_section(
    colors: dict,
    browse_cwd: Callable,
    refresh_target_options: Callable[[str], None],
    refresh_dep_quick_text: Callable,
    refresh_dependency_preview: Callable,
) -> AdvancedSettingsSection:
    section, adv_widget, grid = _create_advanced_container()
    controls = _create_advanced_controls(
        colors,
        browse_cwd,
        refresh_target_options,
        refresh_dep_quick_text,
        refresh_dependency_preview,
    )
    _layout_advanced_controls(grid, controls)

    section.body_layout.addWidget(adv_widget)
    section.setVisible(False)
    return AdvancedSettingsSection(
        section=section,
        cwd_row=controls.cwd_row,
        cwd_label=controls.cwd_label,
        cwd_edit=controls.cwd_edit,
        browse_cwd_button=controls.browse_cwd_button,
        sub_workflow_filter=controls.sub_workflow_filter,
        target_search_edit=controls.target_search_edit,
        target_scope_combo=controls.target_scope_combo,
        args_edit=controls.args_edit,
        saved_run_args_edit=controls.saved_run_args_edit,
        output_paths_edit=controls.output_paths_edit,
        theme_edit=controls.theme_edit,
        timeout_spin=controls.timeout_spin,
        retry_spin=controls.retry_spin,
        skip_on_success_check=controls.skip_on_success_check,
        dependency_list=controls.dependency_list,
    )


def _create_advanced_container() -> tuple[CollapsibleSection, QWidget, QGridLayout]:
    section = CollapsibleSection("高级设置", collapsed=True)
    widget = QWidget()
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    grid = QGridLayout(widget)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(8)
    grid.setColumnStretch(1, 1)
    return section, widget, grid


def _create_advanced_controls(
    colors: dict,
    browse_cwd: Callable,
    refresh_target_options: Callable[[str], None],
    refresh_dep_quick_text: Callable,
    refresh_dependency_preview: Callable,
) -> AdvancedSettingsControls:
    cwd_edit, browse_cwd_button, cwd_row, cwd_label = _create_cwd_row(browse_cwd)
    sub_workflow_filter, target_search_edit, target_scope_combo = _create_sub_workflow_filter(
        refresh_target_options
    )
    return AdvancedSettingsControls(
        cwd_row=cwd_row,
        cwd_label=cwd_label,
        cwd_edit=cwd_edit,
        browse_cwd_button=browse_cwd_button,
        sub_workflow_filter=sub_workflow_filter,
        target_search_edit=target_search_edit,
        target_scope_combo=target_scope_combo,
        args_edit=_create_line_edit(
            placeholder='例如: ["--output", "result.txt"]',
            tooltip='始终传给脚本或执行器的固定 JSON 数组参数',
        ),
        saved_run_args_edit=_create_line_edit(
            placeholder='例如: ["--year", "2026"]',
            tooltip='没有本次运行覆盖时使用的 JSON 数组参数；固定参数始终保留',
        ),
        # ROI-2: 显式输出声明；监听冲突检测优先使用声明，推断仅作未声明步骤的兜底
        output_paths_edit=_create_line_edit(
            placeholder="例如: D:/数据/基础文件; D:/报表/月报.xlsx（多个用 ; 分隔）",
            tooltip="声明本步骤写出的目录/文件；监听冲突检测优先使用此声明（留空则按参数与步骤类型推断）",
        ),
        theme_edit=_create_line_edit(
            placeholder="留空使用工作流默认主题",
            tooltip="图表类步骤可覆盖工作流默认主题；留空则继承工作流配置",
        ),
        timeout_spin=_create_spin_box(
            minimum=0,
            maximum=86_400,
            suffix=" 秒",
            tooltip="单步骤最长运行时间；0 表示不限制",
            special_value_text="不限制",
        ),
        retry_spin=_create_spin_box(
            minimum=0,
            maximum=99,
            suffix=" 次",
            tooltip="该步骤失败后的自动重试次数",
        ),
        skip_on_success_check=_create_skip_on_success_check(),
        dependency_list=_create_dependency_picker(
            colors,
            refresh_dep_quick_text,
            refresh_dependency_preview,
        ),
    )


def _layout_advanced_controls(grid: QGridLayout, controls: AdvancedSettingsControls) -> None:
    row = 0
    row = _add_labeled_widget(grid, row, controls.cwd_label, controls.cwd_row)
    grid.addWidget(controls.sub_workflow_filter, row, 0, 1, 2)
    row += 1
    row = _add_labeled_widget(grid, row, _fixed_label("固定参数", tooltip="每次运行都会附加的 JSON 数组"), controls.args_edit)
    row = _add_labeled_widget(
        grid,
        row,
        _fixed_label("保存运行参数", tooltip="可在运行前临时覆盖；JSON 数组"),
        controls.saved_run_args_edit,
    )
    row = _add_labeled_widget(
        grid,
        row,
        _fixed_label("输出目录", tooltip="本步骤写出的目录/文件，多个用 ; 分隔"),
        controls.output_paths_edit,
    )
    row = _add_labeled_widget(grid, row, _fixed_label("主题"), controls.theme_edit)
    row = _add_labeled_widget(grid, row, _fixed_label("超时"), controls.timeout_spin)
    row = _add_labeled_widget(grid, row, _fixed_label("重试"), controls.retry_spin)
    row = _add_labeled_widget(grid, row, _fixed_label("成功跳过"), controls.skip_on_success_check)
    _add_labeled_widget(grid, row, _fixed_label("依赖明细"), controls.dependency_list)


def _add_labeled_widget(grid: QGridLayout, row: int, label: QLabel, widget: QWidget) -> int:
    grid.addWidget(label, row, 0)
    grid.addWidget(widget, row, 1)
    return row + 1


def _create_dependency_list(title: str, parent_layout: QHBoxLayout, navigate_from_item: Callable) -> QListWidget:
    column = QWidget()
    column_layout = QVBoxLayout(column)
    column_layout.setContentsMargins(0, 0, 0, 0)
    column_layout.setSpacing(6)
    column_layout.addWidget(QLabel(title))

    list_widget = QListWidget()
    list_widget.setMaximumHeight(92)
    list_widget.itemDoubleClicked.connect(lambda item: navigate_from_item(item))
    column_layout.addWidget(list_widget)
    parent_layout.addWidget(column, stretch=1)
    return list_widget


def _create_cwd_row(browse_cwd: Callable) -> tuple[QLineEdit, QPushButton, QWidget, QLabel]:
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)

    cwd_edit = _create_line_edit(
        placeholder="留空使用脚本所在目录",
        tooltip="留空时使用脚本所在目录；需要指定相对路径基准时再填写",
    )
    layout.addWidget(cwd_edit)

    browse_button = QPushButton("浏览")
    browse_button.setFixedSize(56, 30)
    browse_button.setAccessibleName("浏览工作目录")
    browse_button.setToolTip("浏览并选择工作目录")
    browse_button.clicked.connect(browse_cwd)
    layout.addWidget(browse_button)

    row = QWidget()
    row.setLayout(layout)
    return cwd_edit, browse_button, row, _fixed_label("工作目录")


def _create_sub_workflow_filter(
    refresh_target_options: Callable[[str], None],
) -> tuple[QWidget, QLineEdit, QComboBox]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    search_row = QWidget()
    search_layout = QHBoxLayout(search_row)
    search_layout.setContentsMargins(0, 0, 0, 0)
    search_layout.setSpacing(8)
    search_layout.addWidget(_fixed_label("搜索"))

    search_edit = _create_line_edit(
        placeholder="输入关键词过滤...",
        tooltip="按名称过滤目标工作流",
    )
    search_edit.textChanged.connect(lambda text: refresh_target_options(text))
    search_layout.addWidget(search_edit, stretch=1)
    layout.addWidget(search_row)

    scope_row = QWidget()
    scope_layout = QHBoxLayout(scope_row)
    scope_layout.setContentsMargins(0, 0, 0, 0)
    scope_layout.setSpacing(8)
    scope_layout.addWidget(_fixed_label("范围"))

    scope_combo = QComboBox()
    scope_combo.addItem("全部", "all")
    scope_combo.addItem("最近使用", "recent")
    scope_combo.setFixedHeight(30)
    scope_combo.setMinimumContentsLength(0)
    scope_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    scope_combo.setToolTip("选择目标工作流的过滤范围")
    scope_combo.currentIndexChanged.connect(lambda _index: refresh_target_options(search_edit.text()))
    scope_combo.setFixedWidth(88)
    scope_layout.addWidget(scope_combo)
    scope_layout.addStretch(1)
    layout.addWidget(scope_row)

    widget.setVisible(False)
    return widget, search_edit, scope_combo


def _create_line_edit(placeholder: str = "", tooltip: str = "") -> QLineEdit:
    edit = QLineEdit()
    edit.setFixedHeight(30)
    edit.setMinimumWidth(0)
    edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    if tooltip:
        edit.setToolTip(tooltip)
    return edit


def _create_spin_box(
    minimum: int,
    maximum: int,
    suffix: str,
    tooltip: str,
    special_value_text: str = "",
) -> QSpinBox:
    spin = QSpinBox()
    spin.setFixedHeight(30)
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setValue(minimum)
    spin.setToolTip(tooltip)
    if special_value_text:
        spin.setSpecialValueText(special_value_text)
    return spin


def _create_skip_on_success_check() -> QCheckBox:
    checkbox = QCheckBox("启用")
    checkbox.setToolTip("勾选后，若上次运行该步骤成功，本次将自动跳过")
    return checkbox


def _create_dependency_picker(
    colors: dict,
    refresh_dep_quick_text: Callable,
    refresh_dependency_preview: Callable,
) -> QListWidget:
    dep_list = QListWidget()
    dep_list.setMaximumHeight(108)
    dep_list.setToolTip("自定义当前步骤的单独依赖；阶段顺序仍然是大顺序屏障")
    dep_list.setStyleSheet(
        f"""
        QListWidget::indicator {{
            width: 14px;
            height: 14px;
            border: 1px solid {colors['indicator_border']};
            border-radius: 4px;
            background: {colors['indicator_bg']};
        }}
        QListWidget::indicator:checked {{
            background: {colors['primary']};
            border: 1px solid {colors['primary']};
        }}
        """
    )
    dep_list.itemChanged.connect(lambda _item: (refresh_dep_quick_text(), refresh_dependency_preview()))
    return dep_list


def _fixed_label(text: str, tooltip: str = "") -> QLabel:
    label = QLabel(text)
    label.setFixedWidth(56)
    if tooltip:
        label.setToolTip(tooltip)
    return label
