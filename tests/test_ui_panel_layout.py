# -*- coding: utf-8 -*-
"""主窗口面板布局计算测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ui.panel_layout import (
    border_button_x,
    expanded_splitter_sizes,
    panel_toggle_text,
    run_splitter_sizes,
    visible_run_splitter_sizes,
)


def test_run_splitter_sizes_returns_copies_of_known_profiles():
    running = run_splitter_sizes("running")
    running[0] = 1

    assert run_splitter_sizes("running") == [320, 620]
    assert run_splitter_sizes("idle") == [360, 560]
    assert run_splitter_sizes("unknown") == [360, 560]


def test_panel_toggle_text_matches_left_and_right_directions():
    assert panel_toggle_text("left", True) == "◀"
    assert panel_toggle_text("left", False) == "▶"
    assert panel_toggle_text("right", True) == "▶"
    assert panel_toggle_text("right", False) == "◀"


def test_panel_toggle_text_rejects_unknown_side():
    with pytest.raises(ValueError, match="未知面板方向"):
        panel_toggle_text("center", True)


def test_expanded_splitter_sizes_restores_panel_with_minimum():
    assert expanded_splitter_sizes(
        [0, 700, 300],
        panel_index=0,
        last_size=180,
        minimum_size=200,
    ) == [200, 700, 300]
    assert expanded_splitter_sizes(
        [240, 700, 0],
        panel_index=-1,
        last_size=360,
        minimum_size=320,
    ) == [240, 700, 360]


def test_expanded_splitter_sizes_returns_none_for_invalid_index():
    assert expanded_splitter_sizes(
        [240, 700],
        panel_index=3,
        last_size=360,
        minimum_size=320,
    ) is None


def test_border_button_x_stays_inside_parent_bounds():
    assert border_button_x(edge_x=0, button_width=20, parent_width=1100) == 0
    assert border_button_x(edge_x=1099, button_width=20, parent_width=1100) == 1080
    assert border_button_x(edge_x=240, button_width=20, parent_width=1100) == 230


def test_visible_run_splitter_sizes_restores_hidden_log_area():
    assert visible_run_splitter_sizes([620, 0], available_height=620) == [400, 220]
    assert visible_run_splitter_sizes([300, 260], available_height=560) is None
    assert visible_run_splitter_sizes([300, 0], available_height=300) == [150, 150]
