# -*- coding: utf-8 -*-
"""主窗口运行态计算测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ui.run_state import compute_run_lock_state


def test_compute_run_lock_state_clears_stale_running_id():
    state = compute_run_lock_state(
        running_id=8,
        current_id=8,
        engine_running=False,
    )

    assert state.clear_stale_running is True
    assert state.lock_panels is False
    assert state.show_background_label is False


def test_compute_run_lock_state_locks_current_running_workflow_panels():
    state = compute_run_lock_state(
        running_id=8,
        current_id=8,
        engine_running=True,
    )

    assert state.clear_stale_running is False
    assert state.lock_panels is True
    assert state.show_background_label is False


def test_compute_run_lock_state_shows_background_running_label_when_user_switched_away():
    state = compute_run_lock_state(
        running_id=8,
        current_id=9,
        engine_running=True,
        running_name="月度报表",
    )

    assert state.lock_panels is False
    assert state.show_background_label is True
    assert state.background_label_text == "↻ 后台运行：月度报表"


def test_compute_run_lock_state_hides_background_label_while_stopping():
    state = compute_run_lock_state(
        running_id=8,
        current_id=9,
        engine_running=True,
        stopping=True,
        running_name="月度报表",
    )

    assert state.lock_panels is False
    assert state.show_background_label is False
