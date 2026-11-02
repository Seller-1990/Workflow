# -*- coding: utf-8 -*-
"""Tab and run-splitter styles for the central workspace."""

def build_mode_tabs_stylesheet(tokens: dict, *, radius: int) -> str:
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
            border-top-left-radius: {radius}px;
            border-top-right-radius: {radius}px;
            font-weight: 700;
            text-align: center;
        }}
        QTabBar::tab:hover:!selected {{
            /* #16：QTabBar 的 tab 不是独立控件，无法逐个挂动画，只做静态悬停色 */
            color: {w["ink"]};
            background: {w["panel_soft"]};
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
