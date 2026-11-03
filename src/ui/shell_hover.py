# -*- coding: utf-8 -*-
"""Resolve shell hover colors from the current widget state."""

def hover_palette(tokens: dict, object_name: str):
    """HoverFader 的常态/悬停色表（#16）：返回 (bg_normal, bg_hover, border_normal, border_hover)。

    None 表示该项不做淡入（交由 QSS 静态处理）。终点色与 QSS :hover 完全一致，
    动画结束清掉内联样式后不会跳色。
    """
    w = tokens
    table = {
        "SidebarNav": ("transparent", w["panel_soft"], None, None),
        "ViewSwitch": (None, None, "transparent", w["line"]),
        "IconButton": (None, None, w["line"], w["line_strong"]),
        "PrimaryAction": (w["blue_weak"], w["blue_hover_bg"], None, None),
        "DangerAction": (w["red_weak"], w["red_hover_bg"], None, None),
    }
    return table.get(object_name)


def hover_colors_fn(widget, tokens: dict, *, palette_for=hover_palette):
    """把 hover_palette 的四元组转成 HoverFader 需要的 (normal, hover) 字典对。

    每次悬停时按控件**当前** objectName 取色（运行按钮会在 Primary/Danger 间切换，
    ViewSwitchActive 等不在表内的状态返回 None，交由 QSS 静态处理）。
    """

    def fn():
        pal = palette_for(tokens, widget.objectName())
        if pal is None:
            return None
        bg_n, bg_h, bd_n, bd_h = pal
        normal, hover = {}, {}
        if bg_h is not None:
            normal["background"], hover["background"] = bg_n, bg_h
        if bd_h is not None:
            normal["border-color"], hover["border-color"] = bd_n, bd_h
        return (normal, hover) if hover else None

    return fn
