# -*- coding: utf-8 -*-
"""Retarget presentation-only transitions without changing logical widget state."""

from ui.motion import mix_hex


def interpolate_value(start: float, end: float, t: float) -> float:
    return start + (end - start) * t


def retarget_scalar(widget, target: float, *, animation_allowed) -> None:
    """Continue a reversible scalar transition from the currently displayed value."""
    widget._anim.stop()
    if animation_allowed() and widget._pos != target:
        widget._from, widget._to = widget._pos, target
        widget._anim.start()
    else:
        widget._pos = target
        widget.update()


def retarget_color(widget, color: str, *, animation_allowed) -> None:
    """Preserve the current chunk color when a second status interrupts a fade."""
    if color == widget._color_to and widget._color_anim.state() != widget._color_anim.State.Running:
        if color != widget._chunk_color:
            widget._chunk_color = color
            widget._paint_chunk(color)
        return
    widget._color_anim.stop()
    widget._color_from = widget._chunk_color
    widget._color_to = color
    if animation_allowed() and widget._color_from != color:
        widget._color_anim.start()
    else:
        widget._chunk_color = color
        widget._paint_chunk(color)


def update_color(widget, t: float, *, blend=mix_hex) -> None:
    widget._chunk_color = widget._color_to if t >= 1.0 else blend(widget._color_from, widget._color_to, t)
    widget._paint_chunk(widget._chunk_color)
