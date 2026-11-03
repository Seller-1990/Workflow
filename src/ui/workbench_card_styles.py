# -*- coding: utf-8 -*-
"""Card-only QSS, preserving the board selector cascade."""


def build_card_stylesheet(c: dict, *, radius: int, small_radius: int) -> str:
    return f"""        QFrame#StepCard {{
            background: {c["panel"]};
            border: 1px solid {c["line"]};
            border-left: 4px solid {c["green"]};
            border-radius: {radius}px;
        }}
        QFrame#StepCard:hover {{
            /* #10：悬停只加深边框（灰），不再整卡变主色 */
            border-top: 1px solid {c["line_strong"]};
            border-right: 1px solid {c["line_strong"]};
            border-bottom: 1px solid {c["line_strong"]};
        }}
        QFrame#StepCard[selected="true"] {{
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
            border-radius: {small_radius}px;
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
"""
