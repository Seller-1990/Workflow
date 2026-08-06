# -*- coding: utf-8 -*-
"""强制停止运行历史落库逻辑测试。"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.force_stop import force_cancel_run_record


def test_force_cancel_run_record_does_not_overwrite_terminal_status():
    logs = []
    cancelled_steps = []
    updated = []

    result = force_cancel_run_record(
        10,
        get_status=lambda run_id: "success",
        cancel_pending_step_logs=lambda run_id, message: cancelled_steps.append((run_id, message)) or 2,
        update_run_history=lambda *args, **kwargs: updated.append((args, kwargs)),
        cancelled_status_value="cancelled",
        log_cb=logs.append,
    )

    assert result.status == "already_terminal"
    assert result.existing_status == "success"
    assert result.orphan_steps_cleaned == 2
    assert updated == []
    assert cancelled_steps == [(10, "父运行已终态，孤儿步骤被清理")]
    assert "跳过强制取消" in logs[0]
    assert "清理 2 个孤儿步骤" in logs[1]


def test_force_cancel_run_record_marks_non_terminal_run_cancelled():
    end_time = datetime(2026, 1, 1, 12, 0, 0)
    cancelled_steps = []
    updated = []
    logs = []

    result = force_cancel_run_record(
        11,
        get_status=lambda run_id: "running",
        cancel_pending_step_logs=lambda run_id, message: cancelled_steps.append((run_id, message)) or 1,
        update_run_history=lambda *args, **kwargs: updated.append((args, kwargs)) or True,
        cancelled_status_value="cancelled",
        now=end_time,
        log_cb=logs.append,
    )

    assert result.status == "cancelled"
    assert cancelled_steps == [(11, "用户强制停止")]
    assert updated == [((11,), {"status": "cancelled", "end_time": end_time, "_condition_status": "running"})]
    assert logs == ["已强制停止运行记录 (run_history_id=11)"]


def test_force_cancel_run_record_continues_when_status_read_fails():
    warnings = []
    updated = []

    result = force_cancel_run_record(
        12,
        get_status=lambda run_id: (_ for _ in ()).throw(RuntimeError("db locked")),
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=lambda *args, **kwargs: updated.append((args, kwargs)) or True,
        cancelled_status_value="cancelled",
        warn_cb=lambda template, exc: warnings.append(template % exc),
    )

    assert result.status == "cancelled"
    assert result.existing_status is None
    assert warnings == ["读取 run_history 状态失败: db locked"]
    assert updated
