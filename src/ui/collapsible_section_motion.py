# -*- coding: utf-8 -*-
"""Animate section geometry; logical state and completion signals stay on the widget."""

from ui.motion_state import interpolate_value


def start_animation(widget, *, collapsed_angle: float, expanded_angle: float, size_policy) -> None:
    widget._height_anim.stop()
    widget._angle_anim.stop()

    start_h = widget.height()
    if widget._collapsed:
        target_h = widget._header_height
    else:
        widget.body.setVisible(True)
        target_h = widget._header_height + max(0, widget.body.sizeHint().height())
    widget._height_from, widget._height_to = start_h, target_h
    # 动画期间解除锁定，由 maximumHeight 逐帧收放
    widget.setSizePolicy(size_policy.Expanding, size_policy.Preferred)
    widget.setMinimumHeight(0)
    widget.setMaximumHeight(start_h)
    widget._height_anim.start()

    widget._angle_from = widget._angle
    widget._angle_to = collapsed_angle if widget._collapsed else expanded_angle
    widget._angle_anim.start()
    widget.btn_toggle.setToolTip("展开" if widget._collapsed else "折叠")


def on_height(widget, t: float) -> None:
    h = round(interpolate_value(widget._height_from, widget._height_to, t))
    widget.setMaximumHeight(max(widget._header_height, h))
    widget._relayout_parent()


def on_angle(widget, t: float) -> None:
    widget._angle = interpolate_value(widget._angle_from, widget._angle_to, t)
    widget._update_chevron()
