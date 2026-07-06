# -*- coding: utf-8 -*-
"""RunHistory / StepLog 一致性收尾测试。"""

import sys
import importlib.util
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _load_finalize_run_record():
    module_path = Path(__file__).resolve().parent.parent / "src" / "engine_core" / "run_finalization.py"
    spec = importlib.util.spec_from_file_location("run_finalization_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.finalize_run_record


finalize_run_record = _load_finalize_run_record()


def test_finalize_cancelled_run_cleans_unfinished_steps_before_run_terminal_status():
    calls = []
    end_time = datetime(2026, 1, 1, 12, 0, 0)

    result = finalize_run_record(
        10,
        status_value="cancelled",
        end_time=end_time,
        cancel_pending_step_logs=lambda run_id, message: calls.append(("steps", run_id, message)) or 2,
        update_run_history=lambda run_id, **kwargs: calls.append(("run", run_id, kwargs)),
    )

    assert result is True
    assert calls == [
        ("steps", 10, "运行已取消，未完成步骤被清理"),
        ("run", 10, {"status": "cancelled", "end_time": end_time}),
    ]


def test_finalize_success_run_does_not_touch_step_logs():
    calls = []
    end_time = datetime(2026, 1, 1, 12, 0, 0)

    result = finalize_run_record(
        11,
        status_value="success",
        end_time=end_time,
        cancel_pending_step_logs=lambda run_id, message: calls.append(("steps", run_id, message)),
        update_run_history=lambda run_id, **kwargs: calls.append(("run", run_id, kwargs)),
    )

    assert result is True
    assert calls == [("run", 11, {"status": "success", "end_time": end_time})]


def test_finalize_run_continues_when_step_cleanup_fails():
    warnings = []
    updates = []

    result = finalize_run_record(
        12,
        status_value="cancelled",
        end_time=datetime(2026, 1, 1, 12, 0, 0),
        cancel_pending_step_logs=lambda run_id, message: (_ for _ in ()).throw(RuntimeError("db locked")),
        update_run_history=lambda run_id, **kwargs: updates.append((run_id, kwargs)),
        warn_cb=lambda template, exc: warnings.append(template % exc),
    )

    assert result is True
    assert warnings == ["批量取消未完成 step_logs 失败: db locked"]
    assert updates


def test_finalize_run_returns_false_when_run_update_fails():
    warnings = []

    result = finalize_run_record(
        13,
        status_value="cancelled",
        end_time=datetime(2026, 1, 1, 12, 0, 0),
        cancel_pending_step_logs=lambda run_id, message: 0,
        update_run_history=lambda run_id, **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")),
        warn_cb=lambda template, exc: warnings.append(template % exc),
    )

    assert result is False
    assert warnings == ["更新运行历史失败: run_history_id=13, disk full"]
