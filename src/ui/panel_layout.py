# -*- coding: utf-8 -*-
"""主窗口面板布局计算逻辑。"""

from __future__ import annotations

RUNNING_SPLITTER_SIZES = [320, 620]
IDLE_SPLITTER_SIZES = [360, 560]
RUN_HISTORY_MIN_VISIBLE_HEIGHT = 180
RUN_LOG_MIN_VISIBLE_HEIGHT = 220


def run_splitter_sizes(profile: str) -> list[int]:
    """返回运行区 splitter 的预设尺寸。"""
    if profile == "running":
        return list(RUNNING_SPLITTER_SIZES)
    return list(IDLE_SPLITTER_SIZES)


def visible_run_splitter_sizes(
    sizes: list[int],
    *,
    available_height: int,
    min_history: int = RUN_HISTORY_MIN_VISIBLE_HEIGHT,
    min_log: int = RUN_LOG_MIN_VISIBLE_HEIGHT,
) -> list[int] | None:
    """返回确保运行日志可见的 splitter 尺寸；无需调整时返回 None。"""
    if len(sizes) < 2:
        return None
    total = sum(max(0, int(size)) for size in sizes[:2])
    if total <= 0:
        total = max(0, int(available_height))
    if total <= 0:
        return None

    history_min = min(int(min_history), max(0, total // 2))
    log_min = min(int(min_log), max(80, total - history_min))
    if total < history_min + log_min:
        log_min = max(80, total // 2)
        history_min = max(0, total - log_min)

    current_history = max(0, int(sizes[0]))
    current_log = max(0, int(sizes[1]))
    if current_history >= history_min and current_log >= log_min:
        return None

    next_log = max(current_log, log_min)
    next_log = min(next_log, max(0, total - history_min))
    return [max(0, total - next_log), next_log]


def panel_toggle_text(side: str, visible: bool) -> str:
    """返回边框折叠按钮文字。"""
    if side == "left":
        return "◀" if visible else "▶"
    if side == "right":
        return "▶" if visible else "◀"
    raise ValueError(f"未知面板方向: {side}")


def border_button_x(*, edge_x: int, button_width: int, parent_width: int) -> int:
    """返回完整落在父窗口内的边框按钮 x 坐标。"""
    max_x = max(0, parent_width - button_width)
    centered_x = edge_x - button_width // 2
    return min(max(0, centered_x), max_x)


def expanded_splitter_sizes(
    sizes: list[int],
    *,
    panel_index: int,
    last_size: int,
    minimum_size: int,
) -> list[int] | None:
    """计算展开面板后的 splitter 尺寸；索引无效时返回 None。"""
    if not sizes:
        return None
    resolved_index = panel_index if panel_index >= 0 else len(sizes) + panel_index
    if resolved_index < 0 or resolved_index >= len(sizes):
        return None

    next_sizes = list(sizes)
    next_sizes[resolved_index] = max(last_size, minimum_size)
    return next_sizes
