# -*- coding: utf-8 -*-
"""RunHistory 已创建但运行初始化失败时的终态回归。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import engine as engine_module
import engine_core.lifecycle as lifecycle
from _schema_guard_utils import _use_temp_database
from engine import RunMode, WorkflowEngine


@pytest.mark.parametrize("failure_point", ("mkdir", "running_update"))
def test_initialization_failure_finalizes_actual_run_history_id(
    monkeypatch, tmp_path, failure_point,
):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("初始化失败")
    db.create_step(workflow.id, "A", script_path="scripts/a.py")
    engine = WorkflowEngine()
    observed = {}
    finalized = []
    try:
        monkeypatch.setattr(lifecycle, "LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(engine, "_cleanup_old_logs_async", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)
        real_begin = engine_module._begin_run
        real_finalize = engine_module._finalize_run

        def capture_begin_failure(**kwargs):
            try:
                return real_begin(**kwargs)
            except lifecycle.BeginRunError as exc:
                observed["context"] = exc.context
                raise

        def capture_finalization(run_history_id, **kwargs):
            finalized.append(run_history_id)
            return real_finalize(run_history_id, **kwargs)

        def capture_failure_point():
            observed["failure_reached"] = True
            observed["active_ids"] = set(engine._active_run_ids)

        monkeypatch.setattr(engine_module, "_begin_run", capture_begin_failure)
        monkeypatch.setattr(engine_module, "_finalize_run", capture_finalization)
        monkeypatch.setattr(engine, "_execute_steps", lambda *_a, **_k: observed.setdefault(
            "steps_executed", True,
        ))

        if failure_point == "mkdir":
            def fail_mkdir(*args, **kwargs):
                capture_failure_point()
                raise OSError("disk full")
            from pathlib import Path as RealPath
            monkeypatch.setattr(RealPath, "mkdir", fail_mkdir)
        else:
            real_update = lifecycle.update_run_history

            def fail_running_update(run_history_id, **kwargs):
                if kwargs.get("status") == "running":
                    capture_failure_point()
                    raise RuntimeError("database unavailable")
                return real_update(run_history_id, **kwargs)
            monkeypatch.setattr(lifecycle, "update_run_history", fail_running_update)

        assert engine.run(workflow.id, RunMode.FULL) is False

        histories = db.get_run_histories_by_workflow(workflow.id)
        assert observed.get("failure_reached") is True
        assert len(histories) == 1
        history = histories[0]
        assert observed["active_ids"] == {history.id}
        assert observed["context"].run_history_id == history.id
        assert observed["context"].run_id == history.run_id
        assert finalized == [history.id]
        assert history.status == "failure"
        assert history.end_time is not None
        assert "steps_executed" not in observed
        assert engine._active_run_ids == set()
        assert engine.current_run_history_id is None
        assert engine.is_running is False
    finally:
        engine.shutdown(wait=False)
