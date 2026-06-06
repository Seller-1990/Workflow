# -*- coding: utf-8 -*-
"""主窗口面板布局计算逻辑。"""

from __future__ import annotations

RUNNING_SPLITTER_SIZES = [320, 620]
IDLE_SPLITTER_SIZES = [360, 560]


def run_splitter_sizes(profile: str) -> list[int]:
    """返回运行区 splitter 的预设尺寸。"""
    if profile == "running":
        return list(RUNNING_SPLITTER_SIZES)
    return list(IDLE_SPLITTER_SIZES)


def panel_toggle_text(side: str, visible: bool) -> str:
    """返回边框折叠按钮文字。"""
    if side == "left":
        return "◀" if visible else "▶"
    if side == "right":
        return "▶" if visible else "◀"
    raise ValueError(f"未知面板方向: {side}")


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
