# -*- coding: utf-8 -*-
"""V9 UI 状态持久化（基于 QSettings）。

复用现有 ``QSettings(APP_NAME, "ui")`` 节点，扩展 5 个键：
- ``main_splitter_sizes``：[left, center, right] JSON
- ``panel_left_collapsed``：bool
- ``panel_right_collapsed``：bool
- ``mode_tabs_current``：int（0=编排, 1=运行, 2=配置）
- ``plan_view_current``：int（0=阶段, 1=列表）

splitter sizes 用 300ms 防抖，避免拖拽时频繁写注册表。
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import QTimer, QSettings

from config import APP_NAME

logger = logging.getLogger(__name__)


def _settings() -> QSettings:
    return QSettings(APP_NAME, "ui")


def save_main_splitter_sizes(sizes: list[int], debounce_timer: QTimer) -> None:
    """防抖保存 splitter sizes（300ms）。"""
    debounce_timer.setProperty("pending_sizes", sizes)
    debounce_timer.start(300)


def flush_splitter_sizes(debounce_timer: QTimer) -> None:
    """防抖定时器触发时实际写入。"""
    sizes = debounce_timer.property("pending_sizes")
    if sizes is None:
        return
    try:
        _settings().setValue("main_splitter_sizes", json.dumps(list(sizes), ensure_ascii=False))
    except Exception as exc:  # broad_except: 持久化失败不应阻塞 UI
        logger.warning("保存 splitter sizes 失败: %s", exc)


def load_main_splitter_sizes(default: list[int]) -> list[int]:
    """读取 splitter sizes，失败 fallback 到 default。"""
    raw = _settings().value("main_splitter_sizes")
    if not raw:
        return default
    try:
        sizes = json.loads(raw)
        if isinstance(sizes, list) and len(sizes) >= 3:
            return [int(s) for s in sizes][:3]
    except (ValueError, TypeError):
        pass
    return default


def save_panel_collapsed(side: str, collapsed: bool) -> None:
    """保存面板折叠状态。

    Args:
        side: "left" 或 "right"
        collapsed: 是否折叠
    """
    try:
        _settings().setValue(f"panel_{side}_collapsed", bool(collapsed))
    except Exception as exc:
        logger.warning("保存面板折叠状态失败 %s: %s", side, exc)


def load_panel_collapsed(side: str, default: bool = False) -> bool:
    """读取面板折叠状态。"""
    return bool(_settings().value(f"panel_{side}_collapsed", default, type=bool))


def save_mode_tabs_current(index: int) -> None:
    """保存当前 Tab 索引。"""
    try:
        _settings().setValue("mode_tabs_current", int(index))
    except Exception as exc:
        logger.warning("保存 Tab 索引失败: %s", exc)


def load_mode_tabs_current(default: int = 0) -> int:
    """读取当前 Tab 索引。"""
    val = _settings().value("mode_tabs_current", default)
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def save_plan_view_current(index: int) -> None:
    """保存编排视图索引（0=阶段, 1=列表）。"""
    try:
        _settings().setValue("plan_view_current", int(index))
    except Exception as exc:
        logger.warning("保存编排视图索引失败: %s", exc)


def load_plan_view_current(default: int = 0) -> int:
    """读取编排视图索引。"""
    val = _settings().value("plan_view_current", default)
    try:
        return int(val)
    except (ValueError, TypeError):
        return default
