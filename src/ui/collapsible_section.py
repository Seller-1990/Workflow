# -*- coding: utf-8 -*-
"""可折叠区块（iOS 极简：左侧箭头 + 标题 + 右侧操作位）

说明：
- 在 QScrollArea 中，若父容器被拉伸到 viewport 高度，而内部没有 spacer，
  Qt 可能会把「多余高度」分配给这些 section，导致折叠态仍占据大量空白。
- 这里在折叠态下强制将 section 高度收敛到 header 高度，并在展开态恢复，
  以获得更符合 iOS/Swiss minimal 的紧凑表现。
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QFrame, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ui.theme import COLORS, CORNER_RADIUS, get_colors


class CollapsibleSection(QFrame):
    """一个带标题栏的可折叠容器。

    - 标题与折叠按钮同一行（避免「按钮单独占一行」的浪费）
    - body_layout 可直接 addWidget/addLayout
    """

    collapsed_changed = Signal(bool)  # collapsed

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

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(int(header_padding), 0, int(header_padding), 0)
        header_layout.setSpacing(8)
        header.setFixedHeight(self._header_height)

        self.btn_toggle = QToolButton()
        self.btn_toggle.setObjectName("sectionChevron")
        self.btn_toggle.setAutoRaise(True)
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.clicked.connect(self.toggle)
        self.btn_toggle.setFixedSize(18, 18)
        header_layout.addWidget(self.btn_toggle, alignment=Qt.AlignVCenter)

        self.title_label = QLabel(title)
        f = self.title_label.font()
        f.setPointSize(int(title_font_size))
        if int(title_weight) >= 700:
            f.setWeight(QFont.Weight.Bold)
        elif int(title_weight) >= 600:
            f.setWeight(QFont.Weight.DemiBold)
        else:
            f.setWeight(QFont.Weight.Normal)
        self.title_label.setFont(f)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()

        self.header_actions = QWidget()
        self.header_actions_layout = QHBoxLayout(self.header_actions)
        self.header_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.header_actions_layout.setSpacing(8)
        header_layout.addWidget(self.header_actions, alignment=Qt.AlignRight | Qt.AlignVCenter)

        root.addWidget(header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(int(body_padding), int(body_top_padding), int(body_padding), int(body_padding))
        self.body_layout.setSpacing(10)
        root.addWidget(self.body)

        # 卡片风格 - 增强视觉层次：白色卡片 + 微妙阴影 + 边框
        self.setStyleSheet(
            f"""
            QFrame#collapsibleSection {{
                border-radius: {CORNER_RADIUS['large']}px;
                background: {COLORS['surface_card']};
                border: 1px solid {COLORS['border_subtle']};
            }}
            QFrame#collapsibleSection:hover {{
                border-color: {COLORS['border']};
            }}
            QToolButton#sectionChevron {{
                color: {COLORS['text_tertiary']};
            }}
            """
        )

        self._apply_state(emit=False)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._apply_state(emit=True)

    def toggle(self):
        self.set_collapsed(not self._collapsed)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.setStyleSheet(
            f"""
            QFrame#collapsibleSection {{
                border-radius: {CORNER_RADIUS['large']}px;
                background: {colors['surface_card']};
                border: 1px solid {colors['border_subtle']};
            }}
            QFrame#collapsibleSection:hover {{
                border-color: {colors['border']};
            }}
            QToolButton#sectionChevron {{
                color: {colors['text_tertiary']};
            }}
            """
        )

    def _apply_state(self, emit: bool):
        self.body.setVisible(not self._collapsed)
        self.btn_toggle.setArrowType(Qt.RightArrow if self._collapsed else Qt.DownArrow)
        self.btn_toggle.setToolTip("展开" if self._collapsed else "折叠")

        # 折叠态：不允许 section 撑满剩余高度
        if self._collapsed:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumHeight(self._header_height)
            self.setMaximumHeight(self._header_height)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)

        # 触发布局重算（避免在 ScrollArea 中出现「折叠后仍占地很大」）
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

        if emit:
            self.collapsed_changed.emit(self._collapsed)
