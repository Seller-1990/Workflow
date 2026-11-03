# -*- coding: utf-8 -*-
"""Build and theme the global progress strip's visual surface."""


def setup_progress_surface(widget, *, progress_type, layout_type):
    layout = layout_type(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    widget._bar = progress_type()
    widget._bar.setTextVisible(False)
    widget._bar.setFixedHeight(widget.VISIBLE_HEIGHT)
    widget._bar.setRange(0, 100)
    widget._bar.setValue(0, animate=False)
    layout.addWidget(widget._bar)

def apply_progress_style(widget, colors: dict) -> None:
    c = colors
    widget.setStyleSheet(f"""
        QFrame#GlobalProgressBar {{
            background: transparent;
            border: none;
        }}
        QProgressBar {{
            background: {c["border_subtle"]};
            border: none;
            border-radius: 0;
        }}
    """)
    widget._paint_chunk(widget._chunk_color)


def paint_progress_chunk(widget, color: str) -> None:
    widget._bar.setStyleSheet(f"""
        QProgressBar::chunk {{
            background: {color};
            border-radius: 0;
        }}
    """)
