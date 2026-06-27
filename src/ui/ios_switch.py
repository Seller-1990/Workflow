# -*- coding: utf-8 -*-
"""iOS 风格开关（避免 QSS 无法绘制「滑块」的限制）"""

from PySide6.QtWidgets import QCheckBox
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter

from ui.theme import COLORS, get_colors


class IosSwitch(QCheckBox):
    """一个轻量 iOS Switch：48×28，白色滑块 24×24（U-P3-10：满足 Win11 最小可点击 32px 要求）。"""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._dark = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 28)
        self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self) -> QSize:
        return QSize(48, 28)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2.0

        # Track：V9.2 用 token（原硬编码 #48484A/#E5E7EB）
        c = get_colors(self._dark)
        track = QColor(c["primary"] if self.isChecked() else c["border"])
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        # Knob：V9.2 用 indicator_bg（原硬编码 #FFFFFF）
        knob_d = 24
        knob_y = (h - knob_d) / 2.0
        knob_x = w - knob_d - 2 if self.isChecked() else 2
        painter.setBrush(QColor(c["indicator_bg"]))
        painter.drawEllipse(int(knob_x), int(knob_y), knob_d, knob_d)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            new_state = not self.isChecked()
            self.setChecked(new_state)
            self.update()
            self.stateChanged.emit(2 if new_state else 0)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            if self.isEnabled():
                new_state = not self.isChecked()
                self.setChecked(new_state)
                self.update()
                self.stateChanged.emit(2 if new_state else 0)
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        self.update()
