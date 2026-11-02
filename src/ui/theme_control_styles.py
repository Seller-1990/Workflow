# -*- coding: utf-8 -*-
"""Reusable control QSS built only from supplied theme colors."""

def build_danger_button_stylesheet(colors: dict, dark: bool, radius: int, padding: str) -> str:
    fg = colors["text_primary"] if dark else colors["text_inverse"]
    return f"""
QPushButton {{
    background: {colors["danger"]};
    color: {fg};
    border: none;
    border-radius: {int(radius)}px;
    padding: {padding};
    font-weight: 700;
    text-align: center;
}}
QPushButton:hover {{
    background: {colors["danger_hover"]};
}}
QPushButton:pressed {{
    background: {colors["danger_pressed"]};
}}
QPushButton:disabled {{
    background: {colors["border"]};
    color: {colors["text_tertiary"]};
}}
"""


def get_checkbox_stylesheet(colors: dict) -> str:
    """普通复选框共用边框和实心选中态，避免透明 QWidget 规则吞掉指示器。"""
    return f"""
    QCheckBox {{
        background: transparent;
        spacing: 6px;
        color: {colors["text_primary"]};
    }}
    QCheckBox:disabled {{ color: {colors["text_tertiary"]}; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {colors["text_tertiary"]};
        border-radius: 4px;
        background: {colors["indicator_bg"]};
    }}
    QCheckBox::indicator:checked, QCheckBox::indicator:indeterminate {{
        background: {colors["primary"]};
        border-color: {colors["primary"]};
    }}
    QCheckBox::indicator:disabled {{
        background: {colors["surface_secondary"]};
        border-color: {colors["text_tertiary"]};
    }}
    QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled {{
        background: {colors["text_secondary"]};
        border-color: {colors["text_secondary"]};
    }}
    QCheckBox::indicator:focus {{ border-color: {colors["primary_aa"]}; }}
    """
