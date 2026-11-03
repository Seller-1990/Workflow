# -*- coding: utf-8 -*-
"""Draw the switch from logical position without changing input semantics."""

from PySide6.QtCore import Qt
from ui.motion_state import interpolate_value


def init_switch_motion(widget, make_variant):
    widget._pos = 1.0 if widget.isChecked() else 0.0
    widget._from = widget._pos
    widget._to = widget._pos
    widget._anim = make_variant("switch", widget, widget._on_anim)
    widget.toggled.connect(widget._on_toggled)


def update_position(widget, t: float) -> None:
    widget._pos = interpolate_value(widget._from, widget._to, t)
    widget.update()


def paint_switch(widget, *, colors, mix_color, painter_type, color_type):
    painter = painter_type(widget)
    painter.setRenderHint(painter_type.Antialiasing)

    w = widget.width()
    h = widget.height()
    radius = h / 2.0

    # Track：V9.2 用 token；开/关两色按滑块位置插值
    c = colors
    track = mix_color(c["border"], c["primary"], widget._pos)
    painter.setPen(Qt.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(0, 0, w, h, radius, radius)

    # Knob：V9.2 用 indicator_bg
    knob_d = 24
    knob_y = (h - knob_d) / 2.0
    knob_x = 2 + (w - knob_d - 4) * widget._pos
    painter.setBrush(color_type(c["indicator_bg"]))
    painter.drawEllipse(int(round(knob_x)), int(knob_y), knob_d, knob_d)
