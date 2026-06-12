# -*- coding: utf-8 -*-
"""Stylesheet builders for MainWindow shell panels."""

from __future__ import annotations


def build_shell_theme_tokens(colors: dict, dark: bool) -> dict:
    if dark:
        return {
            "bg": colors["background"],
            "paper": colors["surface_primary"],
            "workspace": colors["surface_secondary"],
            "panel": colors["surface_card"],
            "panel_soft": colors["surface_secondary"],
            "ink": colors["text_primary"],
            "muted": colors["text_secondary"],
            "faint": colors["text_tertiary"],
            "line": colors["border"],
            "line_strong": "#636366",
            "blue": colors["primary"],
            "blue_hover": colors["primary_hover"],
            "blue_weak": "#1A3A5C",
            "green": colors["success"],
            "green_weak": "#1F3A24",
            "red": colors["danger"],
            "red_weak": "#3A1515",
        }
    return {
        "bg": "#f6f4ef",
        "paper": "#fbfaf6",
        "workspace": "#f6f4ef",
        "panel": "#ffffff",
        "panel_soft": "#f1eee7",
        "ink": "#20242a",
        "muted": "#6c7077",
        "faint": "#8b9098",
        "line": "#ddd8cf",
        "line_strong": "#c9c1b6",
        "blue": "#2458d3",
        "blue_hover": "#1d49b6",
        "blue_weak": "#e9eefc",
        "green": "#247145",
        "green_weak": "#e7f3ea",
        "red": "#b3312a",
        "red_weak": "#f8e4e1",
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
            min-height: 24px;
            padding: 0 4px;
            color: {w["green"]};
            background: transparent;
            font-weight: 700;
        }}
        QPushButton#PrimaryAction {{
            min-height: 38px;
            padding: 0 15px;
            color: #fffdfa;
            background: {w["blue"]};
            border: none;
            border-radius: 8px;
            font-weight: 720;
        }}
        QPushButton#PrimaryAction:hover {{
            background: {w["blue_hover"]};
        }}
        QPushButton#PrimaryAction:disabled {{
            background: {w["line_strong"]};
            color: {w["panel_soft"]};
        }}
        QPushButton#DangerAction {{
            min-height: 38px;
            padding: 0 15px;
            color: #fffdfa;
            background: {w["red"]};
            border: none;
            border-radius: 8px;
            font-weight: 760;
        }}
        QPushButton#DangerAction:hover {{
            background: {w["red"]};
        }}
        QPushButton#DangerAction:disabled {{
            background: {w["red_weak"]};
            color: {w["red"]};
        }}
        QToolButton#IconButton {{
            min-width: 36px;
            min-height: 36px;
            color: {w["muted"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
            border-radius: 8px;
            font-weight: 700;
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
            color: {w["muted"]};
            background: {w["panel"]};
            border: 1px solid {w["line"]};
            border-radius: 8px;
            font-weight: 700;
        }}
    """
