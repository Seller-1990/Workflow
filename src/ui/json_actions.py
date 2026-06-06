# -*- coding: utf-8 -*-
"""MainWindow 的工作流 JSON 导入导出动作。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

JSON_FILE_FILTER = "JSON Files (*.json)"
EXPORT_SUCCESS_NOTE = "Webhook URL 已默认脱敏；完整本机恢复请使用自动备份。"


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
    importer: Callable[[Path], int] | None = None,
    show_information: Callable | None = None,
    show_critical: Callable | None = None,
) -> bool:
    """执行导入动作，返回是否实际完成导入。"""
    file_path = selected_path if selected_path is not None else choose_import_json_path(parent)
    if not file_path:
        return False

    if importer is None:
        from database import import_from_json as importer
    if show_information is None:
        from ui.theme import msg_information as show_information
    if show_critical is None:
        from ui.theme import msg_critical as show_critical

    try:
        count = importer(Path(file_path))
        show_information(parent, dark_mode, "导入成功", f"已导入 {count} 个工作流")
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
