# -*- coding: utf-8 -*-
"""Stylesheet builders for the step table package."""

from __future__ import annotations

from ui.theme import CORNER_RADIUS


def build_table_stylesheet(colors: dict) -> str:
    """Build the QSS used by the step table widget.

    The helper is intentionally pure so theme contracts can be tested without
    constructing Qt widgets.
    """
    return f"""
            QTableWidget {{
                background: transparent;
                border: none;
                border-radius: {CORNER_RADIUS["default"]}px;
            }}
            QWidget {{
                background: transparent;
                border: none;
            }}
            QHeaderView::section {{
                background: {colors["surface_header"]};
                color: {colors["text_secondary"]};
                font-weight: 600;
                border: none;
                padding: 6px 6px;
            }}
            QTableView::item {{
                background: transparent;
                padding: 4px 8px;
                color: {colors["text_primary"]};
            }}
            QTableView::item:selected {{
                background: {colors["selected_bg"]};
                color: {colors["selected_text"]};
            }}
            QTableView::item:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#tableIcon, QPushButton#tableIcon {{
                padding: 0px;
                border-radius: {CORNER_RADIUS["default"]}px;
                min-width: 32px;
                min-height: 32px;
                border: none;
                background: transparent;
            }}
            QToolButton#tableIcon:hover, QPushButton#tableIcon:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#tableIcon:pressed, QPushButton#tableIcon:pressed {{
                background: {colors["selected_bg"]};
            }}
            QToolButton#tableIcon:disabled, QPushButton#tableIcon:disabled {{
                background: transparent;
                border: none;
            }}
            QToolButton#tableDangerIcon, QPushButton#tableDangerIcon {{
                padding: 0px;
                border-radius: {CORNER_RADIUS["default"]}px;
                min-width: 32px;
                min-height: 32px;
                border: none;
                background: transparent;
                color: {colors["danger"]};
            }}
            QToolButton#tableDangerIcon:hover, QPushButton#tableDangerIcon:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#tableDangerIcon:pressed, QPushButton#tableDangerIcon:pressed {{
                background: {colors["pressed"]};
            }}
            QToolButton#tableDangerIcon:disabled, QPushButton#tableDangerIcon:disabled {{
                background: transparent;
                border: none;
            }}

            QCheckBox {{
                background: transparent;
                border: none;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1.5px solid {colors["border"]};
                border-radius: 4px;
                background: {colors["background"]};
            }}
            QCheckBox::indicator:checked {{
                background: {colors["primary"]};
                border: 1.5px solid {colors["primary"]};
            }}

            /* Stage header action pill (iOS-like compact toolbar) */
            QFrame#stagePill {{
                background: {colors["background"]};
                border: 1px solid {colors["border"]};
                border-radius: {CORNER_RADIUS["default"]}px;
            }}
            QToolButton#stagePillBtn {{
                padding: 0px;
                border: 0px;
                border-radius: {CORNER_RADIUS["small"]}px;
                background: transparent;
            }}
            QToolButton#stagePillBtn:hover {{
                background: {colors["hover"]};
            }}
            QToolButton#stagePillBtn:pressed {{
                background: {colors["pressed"]};
            }}
            QToolButton#stagePillBtn:disabled {{
                background: transparent;
            }}
        """
