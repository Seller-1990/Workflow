# -*- coding: utf-8 -*-
"""Stylesheet builders for MainWindow shell panels."""

from __future__ import annotations

from ui import shell_hover
from ui.mode_tabs_styles import build_mode_tabs_stylesheet
from ui.motion import mix_hex, rgba
from ui.theme import CORNER_RADIUS

# UI 精修 2026-10 O-2：圆角统一引用 CORNER_RADIUS；例外（保持字面量）：
# RunSplitter 把手 2px（细条装饰，非控件圆角）。
_R = CORNER_RADIUS["default"]


def build_shell_theme_tokens(colors: dict, dark: bool) -> dict:
    # V9：统一调色板——浅色与暗色均从 theme.py 的 COLORS/DARK_COLORS 派生（Indigo + Zinc 灰阶）。
    # AA-safe 强调色（primary_aa/success_aa/danger_aa）保证白底对比度 ≥ 4.5:1。
    # on_primary/indicator_bg/indicator_border 一并透传，token 化硬编码字面量。
    # V9：新增 indigo_weak/violet/teal 透传，消除散落的 blue_weak:#e9eefc。
    return {
        "bg": colors["surface_primary"],
        "paper": colors["surface_card"],
        "workspace": colors["surface_secondary"],
        "panel": colors["surface_card"],
        "panel_soft": colors["surface_secondary"],
        "ink": colors["text_primary"],
        "muted": colors["text_secondary"],
        "faint": colors["text_tertiary"],
        "line": colors["border"],
        "line_strong": colors["divider_strong"],
        "blue": colors["primary_aa"],
        "blue_hover": colors["primary_hover"],
        "blue_weak": colors["indigo_weak"],   # V9：统一 indigo_weak
        "indigo_weak": colors["indigo_weak"],
        "violet": colors["violet"],
        "violet_weak": colors["violet_weak"],
        "teal": colors["teal"],
        "teal_weak": colors["teal_weak"],
        "green": colors["success_aa"],
        "green_weak": colors["success_weak"],
        "red": colors["danger_aa"],
        "red_weak": colors["danger_weak"],
        # 任务5：token 化硬编码字面量
        "on_primary": colors["on_primary"],
        "indicator_bg": colors["indicator_bg"],
        "indicator_border": colors["indicator_border"],
        # UI 精修 2026-10 #1/#2：悬停色由弱底色向强调色混合派生（比常态略深），不再回落到 panel_soft
        "blue_hover_bg": mix_hex(colors["indigo_weak"], colors["primary_aa"], 0.18 if dark else 0.10),
        "red_hover_bg": mix_hex(colors["danger_weak"], colors["danger_aa"], 0.18 if dark else 0.10),
    }


def hover_palette(tokens: dict, object_name: str):
    return shell_hover.hover_palette(tokens, object_name)


def hover_colors_fn(widget, tokens: dict):
    return shell_hover.hover_colors_fn(widget, tokens, palette_for=lambda *args: hover_palette(*args))


def left_panel_stylesheet(tokens: dict) -> str:
    w = tokens
    return f"""
        QFrame#LeftPanel {{
            background: {w["paper"]};
            border-right: 1px solid {w["line"]};
        }}
        QLabel#BrandName {{
            color: {w["ink"]};
            font-size: 18px;
            font-weight: 760;
        }}
        QLabel#BrandSubtitle {{
            color: {w["muted"]};
            font-size: 12px;
        }}
        QLabel#BrandDeveloper {{
            color: {w["faint"]};
            font-size: 10px;
        }}
        QLabel#SidebarLabel {{
            color: {w["muted"]};
            font-size: 11px;
            font-weight: 760;
        }}
        QWidget#foldBar {{
            background: transparent;
        }}
        QPushButton#SidebarNav {{
            min-height: 34px;
            padding: 0 8px;
            color: {w["muted"]};
            background: transparent;
            border: none;
            border-radius: {_R}px;
            text-align: left;
        }}
        QPushButton#SidebarNav:hover {{
            color: {w["ink"]};
            background: {w["panel_soft"]};
        }}
    """


def center_panel_stylesheet(tokens: dict) -> str:
    w = tokens
    return f"""
        QFrame#CenterPanel {{
            background: {w["workspace"]};
        }}
        QLabel#Eyebrow {{
            color: {w["muted"]};
            font-size: 11px;
            font-weight: 760;
        }}
        QLabel#WorkflowTitle {{
            color: {w["ink"]};
            font-size: 28px;
            font-weight: 780;
        }}
        QLabel#WorkflowMeta {{
            color: {w["muted"]};
            font-size: 12px;
        }}
        QLabel#RunStateChip {{
            padding: 0 6px;
            color: {w["green"]};
            background: transparent;
            border: none;
            font-weight: 700;
            font-size: 12px;
            text-align: center;
            qproperty-alignment: AlignCenter;
        }}
        QLabel#RunStateChip[state="running"] {{
            color: {w["blue"]};
        }}
        QLabel#RunStateChip[state="stopping"] {{
            color: {w["red"]};
        }}
        QPushButton#PrimaryAction {{
            min-height: 32px;
            padding: 0 14px;
            color: {w["blue"]};
            background: {w["blue_weak"]};
            border: 1px solid {w["blue"]};
            border-radius: {_R}px;
            font-weight: 700;
            text-align: center;
        }}
        QPushButton#PrimaryAction:hover {{
            background: {w["blue_hover_bg"]};
            border: 1px solid {w["blue_hover"]};
        }}
        QPushButton#PrimaryAction:pressed {{
            background: {w["blue_hover_bg"]};
            border: 1px solid {w["blue"]};
        }}
        QPushButton#PrimaryAction:disabled {{
            background: {w["panel_soft"]};
            color: {w["faint"]};
            border: 1px solid {w["line"]};
        }}
        QPushButton#DangerAction {{
            min-height: 32px;
            padding: 0 14px;
            color: {w["red"]};
            background: {w["red_weak"]};
            border: 1px solid {w["red"]};
            border-radius: {_R}px;
            font-weight: 700;
            text-align: center;
        }}
        QPushButton#DangerAction:hover {{
            background: {w["red_hover_bg"]};
            border: 1px solid {w["red"]};
        }}
        QPushButton#DangerAction:disabled {{
            /* UI 精修 2026-10 #3：停止中保持半透明红，而不是变灰 */
            background: {rgba(w["red_weak"], 0.6)};
            color: {rgba(w["red"], 0.55)};
            border: 1px solid {rgba(w["red"], 0.45)};
        }}
        QToolButton#IconButton {{
            min-width: 36px;
            min-height: 36px;
            padding: 0;
            color: {w["muted"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
            border-radius: {_R}px;
            font-weight: 700;
            text-align: center;
        }}
        QToolButton#IconButton:hover {{
            border-color: {w["line_strong"]};
        }}
        QToolButton#DangerIconButton {{
            min-width: 36px;
            min-height: 36px;
            color: {w["red"]};
            background: {w["red_weak"]};
            border: none;
            border-radius: {_R}px;
            font-weight: 800;
        }}
        QPushButton#ViewSwitch, QPushButton#ViewSwitchActive {{
            min-height: 30px;
            padding: 0 12px;
            border-radius: {_R}px;
            font-weight: 700;
            text-align: center;
        }}
        QPushButton#ViewSwitch {{
            color: {w["muted"]};
            background: transparent;
            border: 1px solid transparent;
        }}
        QPushButton#ViewSwitch:hover {{
            border-color: {w["line"]};
        }}
        QPushButton#ViewSwitchActive {{
            color: {w["ink"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
        }}
    """


def mode_tabs_stylesheet(tokens: dict) -> str:
    return build_mode_tabs_stylesheet(tokens, radius=_R)


def right_panel_stylesheet(tokens: dict) -> str:
    w = tokens
    return f"""
        QFrame#RightPanel {{
            background: {w["paper"]};
            border-left: 1px solid {w["line"]};
        }}
        QLabel#Eyebrow {{
            color: {w["muted"]};
            font-size: 11px;
            font-weight: 760;
        }}
        QLabel#InspectorTitle {{
            color: {w["ink"]};
            font-size: 18px;
            font-weight: 760;
        }}
        QScrollArea#InspectorScroll {{
            background: transparent;
            border: none;
        }}
        QToolButton#IconButton {{
            min-width: 36px;
            min-height: 36px;
            padding: 0;
            color: {w["muted"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
            border-radius: {_R}px;
            font-weight: 700;
            text-align: center;
        }}
    """
