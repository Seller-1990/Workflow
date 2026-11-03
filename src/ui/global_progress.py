# -*- coding: utf-8 -*-
"""V9 全局运行进度条。

顶部 3px 细条（参考 VS Code），数据来自 engine.progress_updated 信号。
- 运行中：Indigo 色填充
- 成功：Emerald 色，停留 800ms 后 200ms 淡出隐藏
- 失败：Red 色，停留 800ms 后 200ms 淡出隐藏
- 隐藏时高度为 0，不占布局空间

UI 精修 2026-10 #7/#8：数值变化 250ms 平滑（SmoothProgressBar），
颜色切换 200ms 渐变，完成后淡出而不是瞬间消失。时长全部取 MOTION_TOKENS。
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QVBoxLayout

from ui import motion_state, progress_styles
from ui.progress_visibility import ProgressVisibility
from ui.motion import SmoothProgressBar, can_animate, duration, make_variant, mix_hex
from ui.theme import get_colors


class GlobalProgressBar(ProgressVisibility, QFrame):
    """全局进度条组件。

    用法：
        bar = GlobalProgressBar()
        bar.set_value(current, total)  # 运行中
        bar.show_running(total)
        bar.show_success()
        bar.show_failure()
    """

    HIDDEN_HEIGHT = 0
    VISIBLE_HEIGHT = 3
    _HIDE_DELAY_MS = duration("hold")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlobalProgressBar")
        self._dark = False
        self._chunk_color = get_colors(False)["primary"]
        self._color_from = self._chunk_color
        self._color_to = self._chunk_color

        progress_styles.setup_progress_surface(self, progress_type=SmoothProgressBar, layout_type=QVBoxLayout)

        self._setup_visibility(
            timer_type=QTimer, opacity_type=QGraphicsOpacityEffect,
            variant_factory=lambda *args: make_variant(*args),
            animation_allowed=lambda: can_animate(self),
        )

        # 颜色渐变（base 200ms）
        self._color_anim = make_variant("base", self, self._on_color)

        self.setFixedHeight(self.HIDDEN_HEIGHT)
        self._apply_style()

    # ------------------------------------------------------------ 样式
    def _apply_style(self) -> None:
        progress_styles.apply_progress_style(self, get_colors(self._dark))

    def refresh_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_style()

    def _paint_chunk(self, color: str) -> None:
        progress_styles.paint_progress_chunk(self, color)

    def _set_chunk_color(self, color: str) -> None:
        """切换填充色：可见时 200ms 渐变，否则直接到位。"""
        motion_state.retarget_color(self, color, animation_allowed=lambda: can_animate(self) and self.height() > 0)

    def _on_color(self, t: float) -> None:
        motion_state.update_color(self, t, blend=mix_hex)

    # ------------------------------------------------------------ 显示/隐藏
    def show_running(self, total: int) -> None:
        """运行开始：显示进度条，归零（不做回退动画）。"""
        self._show_bar()
        self._bar.setRange(0, max(1, total))
        self._bar.setValue(0, animate=False)
        self._set_chunk_color(get_colors(self._dark)["primary"])

    def set_value(self, current: int, total: int) -> None:
        """更新进度（运行中）。"""
        if total <= 0:
            return
        self._show_bar()
        if self._bar.maximum() != total or self._bar.minimum() != 0:
            # 区间变化时按比例换算当前位置，避免平滑动画从错误起点出发
            self._bar.setRange(0, total)
        self._bar.setValue(current)
        self._set_chunk_color(get_colors(self._dark)["primary"])

    def _finish(self, color_key: str) -> None:
        self._show_bar()
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._set_chunk_color(get_colors(self._dark)[color_key])
        self._hide_timer.start(self._HIDE_DELAY_MS)

    def show_success(self) -> None:
        """运行成功：变绿，停留后淡出。"""
        self._finish("success")

    def show_failure(self) -> None:
        """运行失败：变红，停留后淡出。"""
        self._finish("danger")
