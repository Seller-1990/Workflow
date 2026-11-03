# -*- coding: utf-8 -*-
"""Stylesheet helpers for the workbench board."""

from __future__ import annotations

from ui.motion import rgba
from ui.workbench_card_styles import build_card_stylesheet
from ui.theme import CORNER_RADIUS, get_colors

# UI 精修 2026-10 O-2：圆角引用 CORNER_RADIUS；例外（保持字面量）：
# SelectionHint 17px / StatusBadge 10px 为高度一半的胶囊形，StageProgress 2px 为细条。
_R = CORNER_RADIUS["default"]
_RS = CORNER_RADIUS["small"]


def board_tokens(dark: bool) -> dict:
    c = get_colors(dark)
    return {
        "bg": c["background"],
        "panel": c["surface_card"],
        "panel_soft": c["surface_secondary"],
        # O-1：泳道半透明底由 surface_card token 派生（亮/暗各自跟随主题），不再硬编码 rgba 字面量
        "lane": rgba(c["surface_card"], 0.72),
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


# #11：StepCard 左条颜色单一来源（与下方 QSS 的 stepStatus/checkpoint 规则保持一致），
# 供卡片换色 200ms 过渡计算起止色。
_STEP_LEFT_KEYS = {
    "running": "blue",
    "failure": "red",
    "success": "green",
    "cancelled": "amber",
    "skipped": "amber",
}


def step_left_color(c: dict, status: str, checkpoint: bool = False, selected: bool = False) -> str:
    """与 QSS 层叠顺序一致：状态色 > 检查点 violet > 选中 blue > 默认 green。"""
    key = _STEP_LEFT_KEYS.get(status or "idle")
    if key:
        return c[key]
    if checkpoint:
        return c["violet"]
    return c["blue"] if selected else c["green"]


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
            border-radius: {_R}px;
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
            border-radius: {_R}px;
        }}
        QFrame#StageLane[selected="true"] {{
            border: 1px solid {c["blue"]};
        }}
        QFrame#StageLane[dragOver="true"] {{
            border: 2px solid {c["green"]};
        }}
        QLabel#BatchWarning {{
            padding: 8px 12px;
            color: {c["amber"]};
            background: {c["amber_weak"]};
            border: 1px solid {c["amber"]};
            border-radius: {_R}px;
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
{build_card_stylesheet(c, radius=_R, small_radius=_RS)}        QLabel#EmptyState {{
            color: {c["muted"]};
            background: {c["panel"]};
            border: 1px solid {c["line"]};
            border-radius: {_R}px;
            padding: 28px;
        }}
    """
