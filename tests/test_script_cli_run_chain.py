# -*- coding: utf-8 -*-
"""run_arg_overrides 运行链路传递与合并 focused tests."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import RunMode, WorkflowEngine
from engine_core.step_execution import execute_step_attempt
from executors import ExecutorResult


def test_run_forwards_run_arg_overrides_to_execute_steps(monkeypatch, tmp_path: Path):
    """engine.run(..., run_arg_overrides=...) 进入 _execute_steps 同一字典。"""
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(
            id=1,
            uid="wf-1",
            name="主工作流",
            log_retention_days=1,
            single_script_enabled=False,
            parallel_enabled=False,
            get_notify_config=lambda: {},
        )
        steps = [SimpleNamespace(id=1, uid="step-a", order=1, name="A")]
        captured = {}

        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 1 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: steps if workflow_id == 1 else [])
        monkeypatch.setattr(
            "engine_core.lifecycle.create_run_history",
            lambda **kwargs: SimpleNamespace(
                id=11,
                run_id="run-1",
                trace_id=kwargs.get("trace_id") or "trace-1",
                parent_run_id=kwargs.get("parent_run_id"),
            ),
        )
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *a, **k: None)
        monkeypatch.setattr("engine.update_run_history", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_select_steps", lambda *a, **k: steps)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        def fake_execute_steps(
            current_workflow,
            selected_steps,
            run_history_id,
            log_dir,
            signal_policy,
            run_cancel_event=None,
            run_arg_overrides=None,
        ):
            captured["run_arg_overrides"] = run_arg_overrides
            return True

        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        overrides = {"step-a": ["--year", "2025"]}
        ok = engine.run(1, RunMode.FULL, run_arg_overrides=overrides)

        assert ok is True
        assert captured["run_arg_overrides"] == {"step-a": ["--year", "2025"]}
    finally:
        engine.shutdown(wait=False)


def test_execute_steps_forwards_overrides_to_single_step(monkeypatch, tmp_path: Path):
    """_execute_steps 将 run_arg_overrides 传到 _execute_single_step。"""
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(
            id=1,
            parallel_enabled=False,
            single_script_enabled=False,
            max_workers=1,
        )
        step = SimpleNamespace(
            id=1,
            uid="step-a",
            order=1,
            name="A",
            stage_uid=None,
            is_gate=False,
            depends_on="",
        )
        captured = {}

        def fake_execute_single_step(
            current_workflow,
            current_step,
            run_history_id,
            log_dir,
            signal_policy,
            prev_step_status_map=None,
            run_cancel_event=None,
            run_arg_overrides=None,
        ):
            captured["run_arg_overrides"] = run_arg_overrides
            from engine import StepResult

            return StepResult(
                step_id=current_step.id,
                step_name=current_step.name,
                status="success",
                exit_code=0,
            )

        monkeypatch.setattr(engine, "_execute_single_step", fake_execute_single_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)
        monkeypatch.setattr(engine, "compute_batches", lambda wf, steps, stage_map: [list(steps)])
        monkeypatch.setattr(engine, "_build_stage_meta", lambda **kwargs: ({}, [], None))
        monkeypatch.setattr(engine, "_normalize_stage_uid", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_update_execution_progress", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_is_run_cancelled", lambda *a, **k: False)
        monkeypatch.setattr(engine, "_emit_failed_details", lambda *a, **k: None)
        monkeypatch.setattr("engine.get_stage_order_map", lambda workflow_id: {})
        monkeypatch.setattr("engine._build_stage_group_map", lambda **kwargs: {})
        monkeypatch.setattr("engine._describe_batch_mode", lambda batch: "串行")
        monkeypatch.setattr("engine._build_prev_step_status_map", lambda *a, **k: {})

        overrides = {"step-a": ["--year", "2025"]}
        ok = engine._execute_steps(
            workflow,
            [step],
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False, emit_run_signals=False),
            run_arg_overrides=overrides,
        )
        assert ok is True
        assert captured["run_arg_overrides"] == overrides
    finally:
        engine.shutdown(wait=False)


def test_execute_step_attempt_merges_fixed_and_temporary_args(tmp_path: Path):
    """execute_step_attempt 传给 executor 的是 fixed + temporary。"""
    engine = MagicMock()
    engine._is_run_cancelled.return_value = False
    engine._is_non_retryable_executor_result.return_value = False
    engine.run_sub_workflow = MagicMock()
    logs = []
    engine._emit_log.side_effect = logs.append
    engine._finish_step = MagicMock()

    workflow = SimpleNamespace(id=1, chart_theme="default")
    step = SimpleNamespace(
        id=7,
        uid="step-a",
        order=1,
        name="Export",
        script_path="export.py",
        cwd="",
        timeout_seconds=30,
        chart_theme="",
        get_args=lambda: ["--mode", "prod"],
    )
    received = {}

    class FakeExecutor:
        def execute(self, **kwargs):
            received.update(kwargs)
            return ExecutorResult(success=True, exit_code=0)

    result, err = execute_step_attempt(
        engine,
        workflow,
        step,
        FakeExecutor(),
        step_log_id=99,
        step_log_dir=tmp_path,
        cancel_event=__import__("threading").Event(),
        run_cancel_event=__import__("threading").Event(),
        signal_policy=SimpleNamespace(emit_step_signals=False),
        run_arg_overrides={"step-a": ["--year", "2025"]},
    )

    assert err is None
    assert result is not None
    assert received["args"] == ["--mode", "prod", "--year", "2025"]
    assert any("参数:" in msg for msg in logs)


def test_sub_workflow_does_not_inherit_parent_overrides(monkeypatch, tmp_path: Path):
    """子工作流 run 默认 run_arg_overrides 为空，不继承父级临时参数。"""
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(
            id=5,
            uid="wf-child",
            name="子工作流",
            log_retention_days=1,
            single_script_enabled=False,
            parallel_enabled=False,
            get_notify_config=lambda: {},
        )
        captured = {}

        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 5 else None)
        monkeypatch.setattr(
            "engine.get_steps_by_workflow",
            lambda workflow_id: [SimpleNamespace(id=1)] if workflow_id == 5 else [],
        )
        monkeypatch.setattr(
            "engine_core.lifecycle.create_run_history",
            lambda **kwargs: SimpleNamespace(
                id=101,
                run_id="child-run",
                trace_id=kwargs.get("trace_id") or "child-trace",
                parent_run_id=kwargs.get("parent_run_id"),
            ),
        )
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *a, **k: None)
        monkeypatch.setattr("engine.update_run_history", lambda *a, **k: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        def fake_execute_steps(
            current_workflow,
            steps,
            run_history_id,
            log_dir,
            signal_policy,
            run_cancel_event=None,
            run_arg_overrides=None,
        ):
            captured["run_arg_overrides"] = run_arg_overrides
            return True

        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        engine._running = True
        engine._current_run_id = "parent-run"
        engine._current_trace_id = "trace-root"

        ok = engine.run_sub_workflow(5)
        assert ok is True
        assert captured["run_arg_overrides"] in (None, {})
    finally:
        engine.shutdown(wait=False)
