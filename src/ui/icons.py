# -*- coding: utf-8 -*-
"""V9 统一图标库（基于 qtawesome）。

集中定义所有图标的获取逻辑，避免散落在各模块直接调用 qtawesome。
- 主题切换时只需调用 ``apply_icon_theme(dark)`` 刷新颜色缓存
- 所有图标均为 QIcon，可直接用于 QPushButton.setIcon / QToolButton.setIcon / QAction.setIcon
- 若 qtawesome 未安装（如开发环境异常），fallback 到空 QIcon，不阻塞 UI
"""

from __future__ import annotations

import logging

from PySide6.QtGui import QIcon

from ui.theme import get_colors

logger = logging.getLogger(__name__)

try:
    import qtawesome as qta
    _QTA_AVAILABLE = True
except ImportError:  # pragma: no cover - 开发环境异常 fallback
    _QTA_AVAILABLE = False
    logger.warning("qtawesome 未安装，图标将显示为空")


# ── 图标名 → qtawesome key 映射（Font Awesome 5 solid） ──
# 集中管理，避免散落硬编码
_ICON_MAP = {
    # 侧栏
    "sidebar.import": "fa5s.file-import",
    "sidebar.export": "fa5s.file-export",
    "sidebar.webhook": "fa5s.satellite-dish",
    # 运行控制
    "run.start": "fa5s.play",
    "run.stop": "fa5s.stop",
    "run.retry": "fa5s.redo",
    "run.dry": "fa5s.eye",
    "run.all": "fa5s.play-circle",
    "run.from": "fa5s.step-forward",
    "run.only": "fa5s.dot-circle",
    # 步骤类型
    "type.python": "fa5s.python",
    "type.excel": "fa5s.file-excel",
    "type.powerbi": "fa5s.chart-bar",
    "type.subworkflow": "fa5s.project-diagram",
    # 主题
    "theme.dark": "fa5s.moon",
    "theme.light": "fa5s.sun",
    # 通用操作
    "action.save": "fa5s.save",
    "action.delete": "fa5s.trash-alt",
    "action.copy": "fa5s.copy",
    "action.more": "fa5s.ellipsis-h",
    "action.search": "fa5s.search",
    "action.clear": "fa5s.times",
    "action.add": "fa5s.plus",
    "action.refresh": "fa5s.sync",
    # 状态
    "status.success": "fa5s.check-circle",
    "status.failure": "fa5s.times-circle",
    "status.running": "fa5s.spinner",
    "status.cancelled": "fa5s.ban",
    "status.pending": "fa5s.clock",
    # 折叠按钮
    "fold.left": "fa5s.chevron-left",
    "fold.right": "fa5s.chevron-right",
}

# 当前主题色缓存（apply_icon_theme 时设置）；V9.2：默认 None，首次调用时按 dark 取 text_secondary
_current_text_color = None
_current_dark = False  # V9.2：缓存当前主题，供 icon() fallback 使用


def apply_icon_theme(dark: bool) -> None:
    """切换主题时刷新图标颜色缓存。

    Args:
        dark: 是否暗色主题
    """
    global _current_text_color, _current_dark
    _current_dark = dark
    c = get_colors(dark)
    _current_text_color = c["text_secondary"]


def icon(name: str, color: str | None = None) -> QIcon:
    """获取图标。

    Args:
        name: 图标键名（见 _ICON_MAP）
        color: 颜色 hex，None 时用当前主题的 text_secondary

    Returns:
        QIcon（qtawesome 不可用时返回空 QIcon）
    """
    if not _QTA_AVAILABLE:
        return QIcon()
    qta_key = _ICON_MAP.get(name)
    if not qta_key:
        logger.warning("未知图标键: %s", name)
        return QIcon()
    try:
        # V9.2：默认色 None 时 fallback 到 text_secondary（原硬编码 #5E6AD2）
        resolved = color or _current_text_color
        if resolved is None:
            resolved = get_colors(_current_dark)["text_secondary"]
        return qta.icon(qta_key, color=resolved)
    except Exception as exc:  # broad_except: 图标加载失败不应阻塞 UI
        logger.warning("图标加载失败 %s: %s", qta_key, exc)
        return QIcon()


def type_icon(step_type: str, dark: bool = False) -> QIcon:
    """获取步骤类型图标，按类型着色。

    Args:
        step_type: python/excel_powerquery/powerbi_refresh/sub_workflow
        dark: 是否暗色主题（影响颜色）
    """
    from ui.theme import TYPE_TOKENS_LIGHT, TYPE_TOKENS_DARK
    c = get_colors(dark)
    tokens = TYPE_TOKENS_DARK if dark else TYPE_TOKENS_LIGHT
    type_key = step_type if step_type in tokens else "python"
    icon_name = {
        "python": "type.python",
        "excel_powerquery": "type.excel",
        "powerbi_refresh": "type.powerbi",
        "sub_workflow": "type.subworkflow",
    }.get(type_key, "type.python")
    color = tokens[type_key]["fg"]
    # 暗色用 c 中 AA-safe 变体
    if dark:
        color_map = {
            "python": c["primary"],
            "excel_powerquery": c["success"],
            "powerbi_refresh": c["warning"],
            "sub_workflow": c["violet"],
        }
        color = color_map.get(type_key, c["primary"])
    return icon(icon_name, color=color)


def set_icon_button(button, name: str, color: str | None = None) -> None:
    """便捷：为按钮设置图标，文字保留（图标在文字左侧）。

    Args:
        button: QPushButton / QToolButton / QAction
        name: 图标键名
        color: 颜色
    """
    button.setIcon(icon(name, color))


def set_icon_only_button(button, name: str, color: str | None = None) -> None:
    """便捷：为按钮设置图标，并清空文字（纯图标按钮）。

    Args:
        button: QPushButton / QToolButton
        name: 图标键名
        color: 颜色
    """
    button.setIcon(icon(name, color))
    button.setText("")
