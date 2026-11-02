# -*- coding: utf-8 -*-
"""运行开始信号携带引擎实际选步总数。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import RunMode, RunSignalPolicy, WorkflowEngine


@pytest.mark.parametrize(
    ("mode", "step_id", "end_step_id", "expected_total"),
    (
        (RunMode.FULL, None, None, 4),
        (RunMode.STEP_RANGE, 2, 3, 2),
        (RunMode.ONLY_STEP, 3, None, 1),
        (RunMode.RETRY_FAILED, None, None, 2),
    ),
)
def test_workflow_started_reports_selected_step_total(
    monkeypatch, tmp_path, mode, step_id, end_step_id, expected_total,
):
    workflow = SimpleNamespace(
        id=1, uid="wf-total", name="总数", parallel_enabled=False,
        log_retention_days=30, get_notify_config=lambda: {},
    )
    steps = [SimpleNamespace(id=index, uid=f"step-{index}", order=index) for index in range(1, 5)]
    history = SimpleNamespace(id=91, run_id="run-total", trace_id="trace", parent_run_id=None)
    started = []
    engine = WorkflowEngine()
    try:
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: steps)
        monkeypatch.setattr("engine.get_latest_run_history", lambda *args, **kwargs: SimpleNamespace(id=80))
        monkeypatch.setattr(
            "engine.get_step_logs_by_run",
            lambda run_history_id: [
                SimpleNamespace(step_id=1, status="failure"),
                SimpleNamespace(step_id=4, status="failure"),
            ],
        )
        monkeypatch.setattr("engine_core.lifecycle.create_run_history", lambda **kwargs: history)
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path)
        monkeypatch.setattr("risk_path_review.build_run_plan", lambda *args, **kwargs: None)
        monkeypatch.setattr("risk_path_review.evaluate_run_plan", lambda plan: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)
        monkeypatch.setattr(engine, "_execute_steps", lambda *args, **kwargs: True)
        engine.workflow_started.connect(lambda *args: started.append(args))

        assert engine.run(1, mode, step_id=step_id, end_step_id=end_step_id) is True
        assert started == [(1, "run-total", expected_total)]
    finally:
        engine.shutdown(wait=False)


def test_nested_run_signal_policy_suppresses_run_and_progress_signals(monkeypatch, tmp_path):
    workflow = SimpleNamespace(
        id=1, uid="wf-nested", name="嵌套", parallel_enabled=False,
        log_retention_days=30, get_notify_config=lambda: {},
    )
    steps = [SimpleNamespace(id=1, uid="step-1", order=1)]
    history = SimpleNamespace(id=92, run_id="nested-total", trace_id="trace", parent_run_id="parent")
    started = []
    progressed = []
    engine = WorkflowEngine()
    try:
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: steps)
        monkeypatch.setattr("engine_core.lifecycle.create_run_history", lambda **kwargs: history)
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path)
        monkeypatch.setattr("risk_path_review.build_run_plan", lambda *args, **kwargs: None)
        monkeypatch.setattr("risk_path_review.evaluate_run_plan", lambda plan: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)
        monkeypatch.setattr(engine, "_execute_steps", lambda *args, **kwargs: True)
        engine.workflow_started.connect(lambda *args: started.append(args))
        engine.progress_updated.connect(lambda *args: progressed.append(args))
        policy = RunSignalPolicy(
            emit_run_signals=False, emit_step_signals=False,
            emit_progress_signals=False, emit_error_details=False, send_notification=False,
        )

        assert engine.run(1, RunMode.FULL, allow_nested=True, signal_policy=policy) is True
        assert started == []
        assert progressed == []
    finally:
        engine.shutdown(wait=False)
