# -*- coding: utf-8 -*-
"""UI 精修 2026-10：共享动效模块（克制顺滑型）。

所有动效集中在此，时长统一取 ``ui.theme.MOTION_TOKENS``，曲线统一 OutCubic
（循环呼吸为正弦往复，用 Linear 驱动相位，见 ``breath_factor``）。
仅依赖 PySide6，不引入新依赖。

提供：
- ``mix_hex`` / ``rgba``：颜色插值与透明度派生（纯函数，主题 token 也复用）
- ``make_animation`` / ``make_variant``：按 token 名创建动画
- ``HoverFader`` / ``install_hover_fade``：悬停背景/边框 150ms 淡入淡出
- ``BreathingChip``：运行状态标签（200ms 变色 + 文字淡出淡入 + 圆点呼吸）
- ``SmoothProgressBar``：数值 250ms 平滑的 QProgressBar（value() 仍返回逻辑目标值）
- ``CHEVRON``：折叠箭头绘制（可旋转）
"""

from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QProgressBar, QStyle, QStyleOption, QWidget

from ui.theme import MOTION_TOKENS

EASING = QEasingCurve.OutCubic
BREATH_MIN = 0.92  # 圆点呼吸最低不透明度（幅度 8%）


# ---------------------------------------------------------------- 基础工具
def duration(name: str) -> int:
    return int(MOTION_TOKENS[name])


def _parse(color) -> QColor:
    if isinstance(color, QColor):
        return QColor(color)
    if color is None or str(color).strip().lower() == "transparent":
        return QColor(0, 0, 0, 0)
    return QColor(str(color))


def mix_color(a, b, t: float) -> QColor:
    """线性插值两种颜色；透明端沿用另一端的 RGB，只插值 alpha，避免发灰。"""
    ca, cb = _parse(a), _parse(b)
    t = max(0.0, min(1.0, float(t)))
    if ca.alpha() == 0:
        ca = QColor(cb.red(), cb.green(), cb.blue(), 0)
    if cb.alpha() == 0:
        cb = QColor(ca.red(), ca.green(), ca.blue(), 0)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
        round(ca.alpha() + (cb.alpha() - ca.alpha()) * t),
    )


def css_color(color: QColor) -> str:
    if color.alpha() >= 255:
        return color.name()
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha() / 255:.3f})"


def mix_hex(a: str, b: str, t: float) -> str:
    """纯函数：a→b 按 t 混合，返回 QSS 可用颜色串。"""
    return css_color(mix_color(a, b, t))


def rgba(color: str, alpha: float) -> str:
    """由 token 颜色派生半透明色（O-1：泳道色不再硬编码 rgba 字面量）。"""
    c = _parse(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {float(alpha):.2f})"


def make_animation(target: QObject, prop: bytes, token: str, parent: Optional[QObject] = None) -> QPropertyAnimation:
    anim = QPropertyAnimation(target, prop, parent or target)
    anim.setDuration(duration(token))
    anim.setEasingCurve(EASING)
    return anim


def make_variant(token: str, parent: QObject, on_value: Callable[[float], None]) -> QVariantAnimation:
    anim = QVariantAnimation(parent)
    anim.setDuration(duration(token))
    anim.setEasingCurve(EASING)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    return anim


def breath_factor(phase: float) -> float:
    """正弦往复：phase 0→1 一轮，返回 1.0→BREATH_MIN→1.0。"""
    return 1.0 - (1.0 - BREATH_MIN) * math.sin(math.pi * phase) ** 2


def make_breath(parent: QObject, on_value: Callable[[float], None]) -> QVariantAnimation:
    anim = QVariantAnimation(parent)
    anim.setDuration(duration("breath"))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setLoopCount(-1)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    return anim


def can_animate(widget: QWidget) -> bool:
    """不可见（构建期/状态恢复/测试中未显示）时直接跳到终态，不播动画。"""
    try:
        return bool(widget.isVisible())
    except RuntimeError:
        return False


# ---------------------------------------------------------------- 悬停淡入淡出
class HoverFader(QObject):
    """150ms 悬停背景/边框淡入淡出。

    ``colors_fn()`` 返回 ``(normal, hover)``，各为 ``{"background": c, "border-color": c}``
    （键即 QSS 属性名，可任选）；返回 None 表示当前不做悬停动效（如已选中）。
    动画期间给 widget 写临时样式（带 ``#objectName`` 选择器，不波及子控件），
    结束后清空，交还给面板级 QSS 的 :hover 规则（两端颜色一致，无跳变）。
    """

    def __init__(self, widget: QWidget, colors_fn: Callable):
        super().__init__(widget)
        self._w = widget
        self.colors_fn = colors_fn
        self._t = 0.0
        self._pair = None
        self._anim = make_variant("fast", self, self._on_value)
        self._anim.finished.connect(self._on_finished)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        et = event.type()
        if obj is self._w and et in (QEvent.Enter, QEvent.Leave):
            self._start(1.0 if et == QEvent.Enter else 0.0)
        return False

    def _start(self, end: float) -> None:
        pair = self.colors_fn() if self._w.isEnabled() else None
        if pair is None:
            self._anim.stop()
            self._t = 0.0
            self._clear()
            return
        self._pair = pair
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(end)
        self._anim.start()

    def _on_value(self, t: float) -> None:
        self._t = t
        if not self._pair:
            return
        normal, hover = self._pair
        decl = "".join(
            f"{k}: {mix_hex(normal.get(k, 'transparent'), hover[k], t)};" for k in hover
        )
        name = self._w.objectName()
        self._w.setStyleSheet(f"#{name} {{ {decl} }}" if name else decl)

    def _on_finished(self) -> None:
        self._clear()

    def _clear(self) -> None:
        if self._w.styleSheet():
            self._w.setStyleSheet("")

    @property
    def animation(self) -> QVariantAnimation:
        return self._anim


def install_hover_fade(widget: QWidget, colors_fn: Callable) -> HoverFader:
    """幂等安装：重复调用只更新颜色来源（主题切换时使用）。"""
    fader = getattr(widget, "_hover_fader", None)
    if isinstance(fader, HoverFader):
        fader.colors_fn = colors_fn
        return fader
    fader = HoverFader(widget, colors_fn)
    widget._hover_fader = fader
    return fader


# ---------------------------------------------------------------- 运行状态标签
class BreathingChip(QLabel):
    """RunStateChip：setText 立即更新真实文本（可测），绘制层做 100ms 淡出 + 100ms 淡入；
    颜色（来自 QSS color）变化时 200ms 渐变；运行中仅左侧圆点呼吸（1.5s 一轮，≥0.92）。"""

    DOT = "●"

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._prev_text = text
        self._fade = 1.0          # 0..1：<0.5 画旧文本淡出，≥0.5 画新文本淡入
        self._color_from: Optional[QColor] = None
        self._color_to: Optional[QColor] = None
        self._color_t = 1.0
        self._breath = 1.0
        self._fade_anim = make_variant("base", self, self._on_fade)
        self._color_anim = make_variant("base", self, self._on_color)
        self._breath_anim = make_breath(self, self._on_breath)

    # --- 文本淡出淡入
    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        old = self.text()
        super().setText(text)
        if old == text:
            return
        self._prev_text = old
        if can_animate(self):
            self._fade_anim.stop()
            self._fade = 0.0
            self._fade_anim.start()
        else:
            self._fade = 1.0
        self.update()

    def _on_fade(self, v: float) -> None:
        self._fade = v
        self.update()

    def _on_color(self, v: float) -> None:
        self._color_t = v
        self.update()

    def _on_breath(self, phase: float) -> None:
        self._breath = breath_factor(phase)
        self.update()

    # --- 呼吸
    def start_breathing(self) -> None:
        if self._breath_anim.state() != QVariantAnimation.Running:
            self._breath_anim.start()

    def stop_breathing(self) -> None:
        self._breath_anim.stop()
        self._breath = 1.0
        self.update()

    @property
    def is_breathing(self) -> bool:
        return self._breath_anim.state() == QVariantAnimation.Running

    # --- 颜色
    def _display_color(self) -> QColor:
        target = self.palette().color(self.foregroundRole())
        if self._color_to is None:
            self._color_from = QColor(target)
            self._color_to = QColor(target)
        elif target != self._color_to:
            current = mix_color(self._color_from, self._color_to, self._color_t)
            self._color_from, self._color_to = current, QColor(target)
            if can_animate(self):
                self._color_t = 0.0
                self._color_anim.stop()
                self._color_anim.start()
            else:
                self._color_t = 1.0
        return mix_color(self._color_from, self._color_to, self._color_t)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)

        color = self._display_color()
        if self._fade < 0.5:
            text, alpha = self._prev_text, 1.0 - self._fade * 2.0
        else:
            text, alpha = self.text(), (self._fade - 0.5) * 2.0
        if not text:
            return
        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        rect = self.contentsRect()
        dot = text.startswith(self.DOT)
        head = self.DOT if dot else ""
        tail = text[len(head):]
        total = fm.horizontalAdvance(text)
        x = rect.x() + (rect.width() - total) / 2.0
        baseline = rect.y() + (rect.height() + fm.ascent() - fm.descent()) / 2.0
        if head:
            c = QColor(color)
            c.setAlphaF(c.alphaF() * alpha * self._breath)
            painter.setPen(c)
            painter.drawText(QPointF(x, baseline), head)
            x += fm.horizontalAdvance(head)
        c = QColor(color)
        c.setAlphaF(c.alphaF() * alpha)
        painter.setPen(c)
        painter.drawText(QPointF(x, baseline), tail)


# ---------------------------------------------------------------- 平滑进度条
class SmoothProgressBar(QProgressBar):
    """内部以 0..SCALE 细分绘制并做 250ms OutCubic 平滑；对外 API 仍是逻辑区间：
    ``value()/minimum()/maximum()`` 立即返回目标值（测试与业务判断不受动画影响）。"""

    SCALE = 1000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lo, self._hi, self._val = 0, 100, 0
        QProgressBar.setRange(self, 0, self.SCALE)
        QProgressBar.setValue(self, 0)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration("progress"))
        self._anim.setEasingCurve(EASING)
        self._anim.valueChanged.connect(lambda v: QProgressBar.setValue(self, int(v)))

    def _scaled(self, v: int) -> int:
        if self._hi <= self._lo:
            return 0
        v = max(self._lo, min(self._hi, int(v)))
        return round((v - self._lo) * self.SCALE / (self._hi - self._lo))

    def setRange(self, lo: int, hi: int) -> None:  # noqa: N802
        self._lo, self._hi = int(lo), int(hi)
        if self._hi <= self._lo:
            self._anim.stop()
            QProgressBar.setRange(self, 0, 0)  # 忙碌态
        else:
            QProgressBar.setRange(self, 0, self.SCALE)
        self._val = max(self._lo, min(self._hi, self._val)) if self._hi > self._lo else self._lo

    def setMinimum(self, lo: int) -> None:  # noqa: N802
        self.setRange(lo, max(lo, self._hi))

    def setMaximum(self, hi: int) -> None:  # noqa: N802
        self.setRange(min(self._lo, hi), hi)

    def minimum(self) -> int:
        return self._lo

    def maximum(self) -> int:
        return self._hi

    def value(self) -> int:
        return self._val

    def setValue(self, v: int, animate: bool = True) -> None:  # noqa: N802
        self._val = max(self._lo, min(self._hi, int(v))) if self._hi > self._lo else self._lo
        if self._hi <= self._lo:
            return
        target = self._scaled(self._val)
        self._anim.stop()
        current = QProgressBar.value(self)
        if animate and can_animate(self) and current != target and current >= 0:
            self._anim.setStartValue(current)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            QProgressBar.setValue(self, target)

    def reset(self) -> None:
        self._anim.stop()
        self._val = self._lo
        QProgressBar.setValue(self, 0)

    @property
    def animation(self) -> QVariantAnimation:
        return self._anim


# ---------------------------------------------------------------- 折叠箭头
def chevron_icon(color: str, angle: float, size: int = 18, dpr: float = 2.0) -> QIcon:
    """绘制一个 ›（angle=0 指右，90 指下），用于折叠区块箭头旋转动画。"""
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(size / 2.0, size / 2.0)
    p.rotate(angle)
    pen = QPen(QColor(color), 1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    path = QPainterPath()
    path.moveTo(-2.0, -4.0)
    path.lineTo(2.0, 0.0)
    path.lineTo(-2.0, 4.0)
    p.drawPath(path)
    p.end()
    return QIcon(px)


__all__ = [
    "BREATH_MIN",
    "BreathingChip",
    "EASING",
    "HoverFader",
    "SmoothProgressBar",
    "breath_factor",
    "can_animate",
    "chevron_icon",
    "css_color",
    "duration",
    "install_hover_fade",
    "make_animation",
    "make_breath",
    "make_variant",
    "mix_color",
    "mix_hex",
    "rgba",
    "QRectF",
]
