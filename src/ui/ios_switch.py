# -*- coding: utf-8 -*-
"""iOS 风格开关（避免 QSS 无法绘制“滑块”的限制）"""

from PySide6.QtWidgets import QCheckBox
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter

from ui.theme import COLORS


class IosSwitch(QCheckBox):
    """一个轻量 iOS Switch：43×24，白色滑块 20×20。"""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(43, 24)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:
        return QSize(43, 24)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2.0

        # Track
        track = QColor(COLORS["primary"] if self.isChecked() else "#E5E7EB")
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        # Knob
        knob_d = 20
        knob_y = (h - knob_d) / 2.0
        knob_x = w - knob_d - 2 if self.isChecked() else 2
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(int(knob_x), int(knob_y), knob_d, knob_d)

    def mouseReleaseEvent(self, event):
        # 让整个控件区域都可切换，避免命中区过小导致“点击无反应”的体验问题
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self.isChecked())
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)
