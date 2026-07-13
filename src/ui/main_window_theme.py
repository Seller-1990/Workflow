# -*- coding: utf-8 -*-
"""Stylesheet builders for MainWindow shell panels."""

from __future__ import annotations


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
    }


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
            border-radius: 8px;
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
            border-radius: 8px;
            font-weight: 700;
            text-align: center;
        }}
        QPushButton#PrimaryAction:hover {{
            background: {w["panel_soft"]};
            border: 1px solid {w["blue_hover"]};
        }}
        QPushButton#PrimaryAction:disabled {{
            background: {w["line_strong"]};
            color: {w["panel_soft"]};
            border: 1px solid {w["line_strong"]};
        }}
        QPushButton#DangerAction {{
            min-height: 32px;
            padding: 0 14px;
            color: {w["red"]};
            background: {w["red_weak"]};
            border: 1px solid {w["red"]};
            border-radius: 8px;
            font-weight: 700;
            text-align: center;
        }}
        QPushButton#DangerAction:hover {{
            background: {w["red_weak"]};
            border: 1px solid {w["red"]};
        }}
        QPushButton#DangerAction:disabled {{
            background: {w["red_weak"]};
            color: {w["red"]};
            border: 1px solid {w["red_weak"]};
        }}
        QToolButton#IconButton {{
            min-width: 36px;
            min-height: 36px;
            padding: 0;
            color: {w["muted"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
            border-radius: 8px;
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
            border-radius: 8px;
            font-weight: 800;
        }}
        QPushButton#ViewSwitch, QPushButton#ViewSwitchActive {{
            min-height: 30px;
            padding: 0 12px;
            border-radius: 8px;
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
    w = tokens
    return f"""
        QTabWidget::pane {{
            border: none;
            background: transparent;
        }}
        QTabBar::tab {{
            height: 38px;
            padding: 0 15px;
            margin-right: 6px;
            color: {w["muted"]};
            background: transparent;
            border: 1px solid transparent;
            border-bottom: 1px solid {w["line"]};
            border-top-left-radius: 7px;
            border-top-right-radius: 7px;
            font-weight: 700;
            text-align: center;
        }}
        QTabBar::tab:selected {{
            color: {w["blue"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
            border-bottom-color: {w["panel"]};
        }}
        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QSplitter#RunSplitter::handle {{
            background: {w["line"]};
            border-radius: 2px;
            margin: 2px 160px;
        }}
        QSplitter#RunSplitter::handle:hover {{
            background: {w["line_strong"]};
        }}
    """


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
            border-radius: 8px;
            font-weight: 700;
            text-align: center;
        }}
    """
