# -*- coding: utf-8 -*-
"""iOS 风格开关（避免 QSS 无法绘制「滑块」的限制）

UI 精修 2026-10 #15：滑块位置与轨道颜色 180ms（MOTION_TOKENS["switch"]）OutCubic 过渡；
不可见时直接到位。isChecked() 立即反映新状态，动画只影响绘制。
"""

from PySide6.QtWidgets import QCheckBox
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter

from ui import motion_state, switch_presentation
from ui.motion import can_animate, make_variant, mix_color
from ui.theme import get_colors


class IosSwitch(QCheckBox):
    """一个轻量 iOS Switch：48×28，白色滑块 24×24（U-P3-10：满足 Win11 最小可点击 32px 要求）。"""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._dark = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(48, 28)
        self.setFocusPolicy(Qt.StrongFocus)
        # 0.0 = 关，1.0 = 开（绘制位置）
        switch_presentation.init_switch_motion(self, make_variant)

    def sizeHint(self) -> QSize:
        return QSize(48, 28)

    # ------------------------------------------------------------ 动画
    def _on_toggled(self, checked: bool) -> None:
        motion_state.retarget_scalar(self, float(bool(checked)), animation_allowed=lambda: can_animate(self))

    def _on_anim(self, t: float) -> None:
        switch_presentation.update_position(self, t)

    @property
    def animation(self):
        return self._anim

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, _event):
        switch_presentation.paint_switch(self, colors=get_colors(self._dark), mix_color=mix_color, painter_type=QPainter, color_type=QColor)

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self.isChecked())
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            if self.isEnabled():
                self.setChecked(not self.isChecked())
                self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        self.update()
