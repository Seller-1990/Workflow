# -*- coding: utf-8 -*-
"""Step table stylesheet helper tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ui.step_table.styles import build_table_stylesheet
from ui.theme import CORNER_RADIUS, get_colors


def test_build_table_stylesheet_contains_expected_selectors_and_tokens():
    colors = get_colors(False)

    qss = build_table_stylesheet(colors)

    assert "QTableWidget" in qss
    assert "QHeaderView::section" in qss
    assert "QToolButton#tableDangerIcon" in qss
    assert "QFrame#stagePill" in qss
    assert colors["surface_header"] in qss
    assert colors["danger"] in qss
    assert f'border-radius: {CORNER_RADIUS["default"]}px' in qss
    assert f'border-radius: {CORNER_RADIUS["small"]}px' in qss


def test_build_table_stylesheet_uses_supplied_color_mapping():
    colors = dict(get_colors(False))
    colors["surface_header"] = "#ABCDEF"
    colors["selected_bg"] = "#123456"

    qss = build_table_stylesheet(colors)

    assert "#ABCDEF" in qss
    assert "#123456" in qss
