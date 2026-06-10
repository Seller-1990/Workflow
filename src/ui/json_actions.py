# -*- coding: utf-8 -*-
"""MainWindow 的工作流 JSON 导入导出动作。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

JSON_FILE_FILTER = "JSON Files (*.json)"
EXPORT_SUCCESS_NOTE = "Webhook URL 已默认脱敏；完整本机恢复请使用自动备份。"
# 导入告警在成功对话框中最多展示的条数，超出部分折叠为"…等 N 条"
MAX_IMPORT_WARNING_LINES = 10


def _format_import_warnings(warnings: list[str]) -> str:
    """把导入告警拼成多行文本（最多 MAX_IMPORT_WARNING_LINES 行，超出折叠）。"""
    shown = warnings[:MAX_IMPORT_WARNING_LINES]
    lines = [f"[警告] {text}" for text in shown]
    if len(warnings) > len(shown):
        lines.append(f"…等 {len(warnings)} 条")
    return "\n".join(lines)


def choose_import_json_path(parent) -> str:
    from PySide6.QtWidgets import QFileDialog

    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        "导入工作流 JSON",
        "",
        JSON_FILE_FILTER,
    )
    return file_path


def choose_export_json_path(parent) -> str:
    from PySide6.QtWidgets import QFileDialog

    file_path, _ = QFileDialog.getSaveFileName(
        parent,
        "导出工作流 JSON",
        "workflows_export.json",
        JSON_FILE_FILTER,
    )
    return file_path


def import_json_action(
    *,
    parent,
    dark_mode: bool,
    reload_workflows: Callable[[], None],
    selected_path: str | None = None,
    importer: Callable[[Path], object] | None = None,
    show_information: Callable | None = None,
    show_critical: Callable | None = None,
) -> bool:
    """执行导入动作，返回是否实际完成导入。

    importer 默认使用 database.import_from_json_with_warnings（返回 ImportResult）；
    也兼容旧式返回 int 数量的导入函数（此时不展示告警）。
    """
    file_path = selected_path if selected_path is not None else choose_import_json_path(parent)
    if not file_path:
        return False

    if importer is None:
        from database import import_from_json_with_warnings as importer
    if show_information is None:
        from ui.theme import msg_information as show_information
    if show_critical is None:
        from ui.theme import msg_critical as show_critical

    try:
        result = importer(Path(file_path))
        # M2: 兼容两种返回值——ImportResult（含告警）与旧式 int 数量
        imported_count = getattr(result, "imported_count", result)
        warnings = list(getattr(result, "warnings", None) or [])
        message = f"已导入 {imported_count} 个工作流"
        if warnings:
            message += "\n\n" + _format_import_warnings(warnings)
        show_information(parent, dark_mode, "导入成功", message)
        reload_workflows()
        return True
    except Exception as exc:
        show_critical(parent, dark_mode, "导入失败", str(exc))
        return False


def export_json_action(
    *,
    parent,
    dark_mode: bool,
    selected_path: str | None = None,
    exporter: Callable[[Path], None] | None = None,
    show_information: Callable | None = None,
    show_critical: Callable | None = None,
) -> bool:
    """执行导出动作，返回是否实际完成导出。"""
    file_path = selected_path if selected_path is not None else choose_export_json_path(parent)
    if not file_path:
        return False

    if exporter is None:
        from database import export_to_json as exporter
    if show_information is None:
        from ui.theme import msg_information as show_information
    if show_critical is None:
        from ui.theme import msg_critical as show_critical

    try:
        exporter(Path(file_path))
        show_information(
            parent,
            dark_mode,
            "导出成功",
            f"已导出到 {file_path}\n\n{EXPORT_SUCCESS_NOTE}",
        )
        return True
    except Exception as exc:
        show_critical(parent, dark_mode, "导出失败", str(exc))
        return False
