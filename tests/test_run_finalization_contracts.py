# -*- coding: utf-8 -*-
"""Additional pure run-finalization contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.run_finalization import finalize_run_record


def test_finalize_failure_run_marks_unfinished_steps_failed_before_run_terminal_status():
    calls = []
    end_time = datetime(2026, 1, 1, 12, 0, 0)

    result = finalize_run_record(
        14,
        status_value="failure",
        end_time=end_time,
        cancel_pending_step_logs=lambda run_id, message: calls.append(("steps", run_id, message)),
        update_run_history=lambda run_id, **kwargs: calls.append(("run", run_id, kwargs)),
    )

    assert result is True
    assert calls == [
        ("steps", 14, "运行失败，未完成步骤被清理"),
        ("run", 14, {"status": "failure", "end_time": end_time}),
    ]


def test_finalize_run_does_not_swallow_programming_field_errors():
    with pytest.raises(ValueError, match="unknown field"):
        finalize_run_record(
            15,
            status_value="failure",
            end_time=datetime(2026, 1, 1, 12, 0, 0),
            cancel_pending_step_logs=lambda run_id, message: 0,
            update_run_history=lambda run_id, **kwargs: (_ for _ in ()).throw(ValueError("unknown field")),
        )
