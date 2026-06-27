# -*- coding: utf-8 -*-
"""V9 全局运行进度条。

顶部 3px 细条（参考 VS Code），数据来自 engine.progress_updated 信号。
- 运行中：Indigo 色填充
- 成功：Emerald 色，延迟 800ms 后隐藏
- 失败：Red 色，延迟 800ms 后隐藏
- 隐藏时高度为 0，不占布局空间
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QProgressBar, QVBoxLayout

from ui.theme import get_colors


class GlobalProgressBar(QFrame):
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
    _HIDE_DELAY_MS = 800

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlobalProgressBar")
        self._dark = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(self.VISIBLE_HEIGHT)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout.addWidget(self._bar)
        self.setFixedHeight(self.HIDDEN_HEIGHT)
        self._apply_style()

    def _apply_style(self) -> None:
        c = get_colors(self._dark)
        self.setStyleSheet(f"""
            QFrame#GlobalProgressBar {{
                background: transparent;
                border: none;
            }}
            QProgressBar {{
                background: {c["border_subtle"]};
                border: none;
                border-radius: 0;
            }}
            QProgressBar::chunk {{
                background: {c["primary"]};
                border-radius: 0;
            }}
        """)

    def refresh_theme(self, dark: bool) -> None:
        self._dark = dark
        self._apply_style()

    def show_running(self, total: int) -> None:
        """运行开始：显示进度条，归零。"""
        self._hide_timer.stop()
        self._bar.setRange(0, max(1, total))
        self._bar.setValue(0)
        self._set_chunk_color(get_colors(self._dark)["primary"])
        self.setFixedHeight(self.VISIBLE_HEIGHT)

    def set_value(self, current: int, total: int) -> None:
        """更新进度（运行中）。"""
        if total <= 0:
            return
        self._hide_timer.stop()
        self._bar.setRange(0, total)
        self._bar.setValue(current)
        self._set_chunk_color(get_colors(self._dark)["primary"])
        if self.height() != self.VISIBLE_HEIGHT:
            self.setFixedHeight(self.VISIBLE_HEIGHT)

    def show_success(self) -> None:
        """运行成功：变绿，延迟隐藏。"""
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._set_chunk_color(get_colors(self._dark)["success"])
        self._hide_timer.start(self._HIDE_DELAY_MS)

    def show_failure(self) -> None:
        """运行失败：变红，延迟隐藏。"""
        self._set_chunk_color(get_colors(self._dark)["danger"])
        self._hide_timer.start(self._HIDE_DELAY_MS)

    def _set_chunk_color(self, color: str) -> None:
        c = get_colors(self._dark)
        self._bar.setStyleSheet(f"""
            QProgressBar::chunk {{
                background: {color};
                border-radius: 0;
            }}
        """)

    def _hide(self) -> None:
        self.setFixedHeight(self.HIDDEN_HEIGHT)
