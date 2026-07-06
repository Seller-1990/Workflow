# -*- coding: utf-8 -*-
"""主窗口运行态计算测试。"""

import sys
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _load_run_state_module():
    module_path = Path(__file__).resolve().parent.parent / "src" / "ui" / "run_state.py"
    spec = importlib.util.spec_from_file_location("run_state_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_run_state = _load_run_state_module()
compute_header_run_state = _run_state.compute_header_run_state
compute_run_lock_state = _run_state.compute_run_lock_state


def test_compute_header_run_state_prioritizes_stopping_over_running():
    assert compute_header_run_state(engine_running=True, stopping=True) == "stopping"


def test_compute_header_run_state_tracks_running_and_idle():
    assert compute_header_run_state(engine_running=True, stopping=False) == "running"
    assert compute_header_run_state(engine_running=False, stopping=False) == "idle"


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
