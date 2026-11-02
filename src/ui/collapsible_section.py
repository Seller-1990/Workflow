# -*- coding: utf-8 -*-
"""可折叠区块（iOS 极简：左侧箭头 + 标题 + 右侧操作位）

说明：
- 在 QScrollArea 中，若父容器被拉伸到 viewport 高度，而内部没有 spacer，
  Qt 可能会把「多余高度」分配给这些 section，导致折叠态仍占据大量空白。
- 这里在折叠态下强制将 section 高度收敛到 header 高度，并在展开态恢复，
  以获得更符合 iOS/Swiss minimal 的紧凑表现。
- UI 精修 2026-10 #13：展开/折叠做 200ms 高度过渡 + 150ms 箭头旋转（OutCubic），
  动画结束后回到原有的高度锁定逻辑（_apply_state）；不可见时直接跳到终态。
- #14：样式统一由 _stylesheet() 生成，构造时即按 self._dark 取色（不再写死浅色 COLORS）。
"""

import sys

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame, QSizePolicy
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont

from ui import collapsible_section_build, collapsible_section_motion
from ui.motion import can_animate, chevron_icon, make_variant
from ui.theme import CORNER_RADIUS, get_colors

_MAX_H = 16777215
_ANGLE_COLLAPSED = 0.0   # › 指右
_ANGLE_EXPANDED = 90.0   # › 指下


class CollapsibleSection(QFrame):
    """一个带标题栏的可折叠容器。

    - 标题与折叠按钮同一行（避免「按钮单独占一行」的浪费）
    - body_layout 可直接 addWidget/addLayout
    """

    collapsed_changed = Signal(bool)  # collapsed
    collapse_requested = Signal(bool)  # next collapsed state; emitted before animation

    def __init__(
        self,
        title: str,
        collapsed: bool = False,
        parent=None,
        *,
        header_height: int = 44,
        title_font_size: int = 14,
        title_weight: int = 600,
        header_padding: int = 12,
        body_padding: int = 12,
        body_top_padding: int = 0,
    ):
        super().__init__(parent)
        self.setObjectName("collapsibleSection")
        self._dark = False
        self._collapsed = bool(collapsed)
        self._header_height = int(header_height)
        self._angle = _ANGLE_COLLAPSED if self._collapsed else _ANGLE_EXPANDED

        collapsible_section_build.setup_section_content(
            self, header_padding=header_padding, title=title, title_font_size=title_font_size,
            title_weight=title_weight, body_padding=body_padding, body_top_padding=body_top_padding,
            ui=sys.modules[__name__],
        )

        # 动画：高度 200ms（base）、箭头 150ms（fast）
        self._height_from = 0
        self._height_to = 0
        self._height_anim = make_variant("base", self, self._on_height)
        self._height_anim.finished.connect(self._on_height_finished)
        self._angle_from = self._angle
        self._angle_to = self._angle
        self._angle_anim = make_variant("fast", self, self._on_angle)

        self.setStyleSheet(self._stylesheet())
        self._apply_state(emit=False)

    # ------------------------------------------------------------ 样式
    def _stylesheet(self) -> str:
        return collapsible_section_build.section_stylesheet(
            self, colors=get_colors(self._dark), radius=CORNER_RADIUS["large"],
        )

    def _update_chevron(self) -> None:
        color = get_colors(self._dark)["text_tertiary"]
        self.btn_toggle.setIcon(chevron_icon(color, self._angle))

    # ------------------------------------------------------------ 状态
    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    @property
    def collapsed_height(self) -> int:
        return self._header_height

    def set_collapsed(self, collapsed: bool):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.collapse_requested.emit(collapsed)
        if can_animate(self):
            self._start_animation()
        else:
            self._height_anim.stop()
            self._angle_anim.stop()
            self._angle = _ANGLE_COLLAPSED if collapsed else _ANGLE_EXPANDED
            self._apply_state(emit=True)

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        self.setStyleSheet(self._stylesheet())
        self._update_chevron()

    # ------------------------------------------------------------ 动画
    def _start_animation(self) -> None:
        collapsible_section_motion.start_animation(
            self, collapsed_angle=_ANGLE_COLLAPSED, expanded_angle=_ANGLE_EXPANDED, size_policy=QSizePolicy,
        )

    def _on_height(self, t: float) -> None:
        collapsible_section_motion.on_height(self, t)

    def _on_height_finished(self) -> None:
        self._angle = self._angle_to
        self._apply_state(emit=True)

    def _on_angle(self, t: float) -> None:
        collapsible_section_motion.on_angle(self, t)

    def _relayout_parent(self) -> None:
        self.updateGeometry()
        try:
            p = self.parentWidget()
            if p:
                p.updateGeometry()
                lay = p.layout()
                if lay:
                    lay.invalidate()
        except Exception:
            pass

    def _apply_state(self, emit: bool):
        self.body.setVisible(not self._collapsed)
        self._update_chevron()
        self.btn_toggle.setToolTip("展开" if self._collapsed else "折叠")

        # 折叠态：不允许 section 撑满剩余高度
        if self._collapsed:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumHeight(self._header_height)
            self.setMaximumHeight(self._header_height)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.setMinimumHeight(0)
            self.setMaximumHeight(_MAX_H)

        # 触发布局重算（避免在 ScrollArea 中出现「折叠后仍占地很大」）
        self._relayout_parent()

        if emit:
            self.collapsed_changed.emit(self._collapsed)
