# -*- coding: utf-8 -*-
"""Stylesheet helpers for the workbench board."""

from __future__ import annotations

from ui.theme import get_colors


def board_tokens(dark: bool) -> dict:
    c = get_colors(dark)
    return {
        "bg": c["background"],
        "panel": c["surface_card"],
        "panel_soft": c["surface_secondary"],
        "lane": "rgba(255, 255, 255, 0.72)" if not dark else "rgba(44, 44, 46, 0.72)",
        "ink": c["text_primary"],
        "muted": c["text_secondary"],
        "line": c["border"],
        "line_strong": c["divider_strong"],
        "blue": c["primary"],
        "blue_weak": c["indigo_weak"],
        "green": c["success"],
        "green_weak": c["success_weak"],
        "amber": c["warning"],
        "amber_weak": c["warning_weak"],
        "red": c["danger"],
        "red_weak": c["danger_weak"],
        "violet": c["violet"],
        "violet_weak": c["violet_weak"],
    }


def build_board_stylesheet(c: dict) -> str:
    return f"""
        QFrame#BoardToolbar {{
            background: transparent;
        }}
        QLabel#SelectionHint {{
            min-height: 34px;
            padding: 0 12px;
            color: {c["green"]};
            background: {c["green_weak"]};
            border-radius: 17px;
            font-weight: 650;
        }}
        QPushButton#GhostButton {{
            min-height: 34px;
            padding: 0 13px;
            color: {c["ink"]};
            background: {c["panel"]};
            border: 1px solid {c["line"]};
            border-radius: 8px;
            font-weight: 700;
        }}
        QPushButton#GhostButton:hover {{
            border-color: {c["line_strong"]};
        }}
        QPushButton#GhostButton:disabled {{
            color: {c["muted"]};
            background: {c["panel_soft"]};
        }}
        QScrollArea#StageBoardScroll {{
            background: transparent;
            border: none;
        }}
        QWidget#StageBoard {{
            background: transparent;
        }}
        QFrame#StageLane {{
            background: {c["lane"]};
            border: 1px solid {c["line"]};
            border-radius: 8px;
        }}
        QFrame#StageLane[selected="true"] {{
            border: 1px solid {c["blue"]};
        }}
        QFrame#StageLane[dragOver="true"] {{
            border: 2px solid {c["green"]};
        }}
        QLabel#StageCode {{
            color: {c["blue"]};
            font-size: 11px;
            font-weight: 800;
        }}
        QLabel#StageTitle {{
            color: {c["ink"]};
            font-size: 15px;
            font-weight: 760;
        }}
        QLabel#StageCount {{
            color: {c["muted"]};
            font-size: 12px;
        }}
        QProgressBar#StageProgress {{
            background: {c["panel_soft"]};
            border: none;
            border-radius: 2px;
        }}
        QProgressBar#StageProgress::chunk {{
            background: {c["green"]};
            border-radius: 2px;
        }}
        QProgressBar#StageProgress[stageStatus="running"]::chunk {{
            background: {c["blue"]};
        }}
        QProgressBar#StageProgress[stageStatus="failure"]::chunk {{
            background: {c["red"]};
        }}
        QProgressBar#StageProgress[stageStatus="cancelled"]::chunk {{
            background: {c["amber"]};
        }}
        QFrame#StepCard {{
            background: {c["panel"]};
            border: 1px solid {c["line"]};
            border-left: 4px solid {c["green"]};
            border-radius: 8px;
        }}
        QFrame#StepCard:hover, QFrame#StepCard[selected="true"] {{
            border: 1px solid {c["blue"]};
            border-left: 4px solid {c["blue"]};
            background: {c["blue_weak"]};
        }}
        QFrame#StepCard[checkpoint="true"] {{
            border-left: 4px solid {c["violet"]};
        }}
        QFrame#StepCard[stepStatus="running"] {{
            border-left: 4px solid {c["blue"]};
        }}
        QFrame#StepCard[stepStatus="failure"] {{
            border-left: 4px solid {c["red"]};
        }}
        QFrame#StepCard[stepStatus="success"] {{
            border-left: 4px solid {c["green"]};
        }}
        QFrame#StepCard[stepStatus="cancelled"], QFrame#StepCard[stepStatus="skipped"] {{
            border-left: 4px solid {c["amber"]};
        }}
        QLabel#StepOrder {{
            min-height: 24px;
            padding: 0;
            color: {c["muted"]};
            background: {c["panel_soft"]};
            border-radius: 6px;
            font-size: 12px;
            font-weight: 800;
            text-align: center;
            qproperty-alignment: AlignCenter;
        }}
        QLabel#StatusBadge {{
            padding: 2px 7px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 760;
            text-align: center;
            qproperty-alignment: AlignCenter;
        }}
        QLabel#StatusBadge[stepStatus="running"] {{
            color: {c["blue"]};
            background: {c["blue_weak"]};
        }}
        QLabel#StatusBadge[stepStatus="success"] {{
            color: {c["green"]};
            background: {c["green_weak"]};
        }}
        QLabel#StatusBadge[stepStatus="failure"] {{
            color: {c["red"]};
            background: {c["red_weak"]};
        }}
        QLabel#StatusBadge[stepStatus="cancelled"], QLabel#StatusBadge[stepStatus="skipped"] {{
            color: {c["amber"]};
            background: {c["amber_weak"]};
        }}
        QLabel#StepTitle {{
            color: {c["ink"]};
            font-size: 14px;
            font-weight: 760;
        }}
        QLabel#StepSubtitle {{
            color: {c["muted"]};
            font-size: 12px;
        }}
        QLabel#DurationBadge {{
            color: {c["muted"]};
            font-size: 11px;
            font-weight: 650;
        }}
        QLabel#EmptyState {{
            color: {c["muted"]};
            background: {c["panel"]};
            border: 1px solid {c["line"]};
            border-radius: 8px;
            padding: 28px;
        }}
    """
