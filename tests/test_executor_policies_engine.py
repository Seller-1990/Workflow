# -*- coding: utf-8 -*-
"""引擎步骤执行与子工作流策略测试：取消映射、重试抑制与嵌套取消传递。

拆分自原 test_executor_policies.py（1000 行硬门槛，纯位置迁移）。
"""

import sys
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import WorkflowEngine, StepResult
from executors.base import ExecutorResult
from executors.result_policy import ResultPolicyKeys, build_policy_extra
from executors.sub_workflow_executor import SubWorkflowExecutor


def test_sub_workflow_executor_uses_injected_runner(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    calls = []

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        workflow_runner=lambda workflow_id, reason="manual", cancel_event=None: calls.append(
            (workflow_id, reason, cancel_event is not None)
        ) or True,
    )

    assert result.success is True
    assert calls == [(5, "sub_workflow", True)]


def test_sub_workflow_executor_returns_result_when_runner_raises(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    def workflow_runner(*args, **kwargs):
        raise RuntimeError("boom")

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        workflow_runner=workflow_runner,
    )

    assert result.success is False
    assert result.exit_code == 1
    assert "子工作流执行异常" in (result.error_message or "")
    assert "boom" in (result.error_message or "")


def test_engine_run_sub_workflow_reuses_parent_context_without_lock_conflict(monkeypatch, tmp_path: Path):
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
        calls = {}

        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 5 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: [SimpleNamespace(id=1)] if workflow_id == 5 else [])

        def fake_create_run_history(**kwargs):
            calls["create_run_history"] = kwargs
            return SimpleNamespace(
                id=101,
                run_id="child-run",
                trace_id=kwargs.get("trace_id") or "child-trace",
                parent_run_id=kwargs.get("parent_run_id"),
            )

        def fake_execute_steps(current_workflow, steps, run_history_id, log_dir, signal_policy, run_cancel_event=None):
            calls["execute_steps"] = {
                "workflow": current_workflow,
                "steps": steps,
                "run_history_id": run_history_id,
                "signal_policy": signal_policy,
                "run_cancel_event": run_cancel_event,
            }
            return True

        monkeypatch.setattr("engine.update_run_history", lambda *args, **kwargs: None)
        # CA2: 生命周期 DB 调用现在通过 engine_core.lifecycle。
        monkeypatch.setattr("engine_core.lifecycle.create_run_history", fake_create_run_history)
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        engine._running = True
        engine._current_run_id = "parent-run"
        engine._current_trace_id = "trace-root"

        result = engine.run_sub_workflow(5)

        assert result is True
        assert calls["create_run_history"]["parent_run_id"] == "parent-run"
        assert calls["create_run_history"]["trace_id"] == "trace-root"
        assert calls["execute_steps"]["run_history_id"] == 101
        assert calls["execute_steps"]["signal_policy"].emit_run_signals is False
        assert calls["execute_steps"]["signal_policy"].emit_step_signals is False
        assert calls["execute_steps"]["run_cancel_event"] is None
        assert engine._running is True
        assert engine._current_run_id == "parent-run"
        assert engine._current_trace_id == "trace-root"
    finally:
        engine.shutdown(wait=False)


def test_engine_run_sub_workflow_forwards_nested_cancel_event(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    cancel_event = threading.Event()
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
        calls = {}

        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 5 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: [SimpleNamespace(id=1)] if workflow_id == 5 else [])

        def fake_create_run_history(**kwargs):
            return SimpleNamespace(
                id=101,
                run_id="child-run",
                trace_id=kwargs.get("trace_id") or "child-trace",
                parent_run_id=kwargs.get("parent_run_id"),
            )

        def fake_execute_steps(current_workflow, steps, run_history_id, log_dir, signal_policy, run_cancel_event=None):
            calls["run_cancel_event"] = run_cancel_event
            return False

        monkeypatch.setattr("engine.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine_core.lifecycle.create_run_history", fake_create_run_history)
        monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        result = engine.run_sub_workflow(5, cancel_event=cancel_event)

        assert result is False
        assert calls["run_cancel_event"] is cancel_event
    finally:
        engine.shutdown(wait=False)


def test_sub_workflow_executor_returns_promptly_when_cancelled_during_wait(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    outer_cancel = threading.Event()
    nested_cancel_events = []

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    def workflow_runner(workflow_id, reason="manual", cancel_event=None):
        nested_cancel_events.append(cancel_event)
        if cancel_event is not None:
            cancel_event.wait(1.0)
        else:
            time.sleep(0.8)
        return False

    threading.Thread(target=lambda: (time.sleep(0.05), outer_cancel.set()), daemon=True).start()

    started_at = time.perf_counter()
    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        timeout=5,
        cancel_event=outer_cancel,
        workflow_runner=workflow_runner,
    )
    elapsed = time.perf_counter() - started_at

    assert result.success is False
    assert result.error_message == "用户取消"
    assert elapsed < 0.3
    assert nested_cancel_events
    assert nested_cancel_events[0] is not None
    assert nested_cancel_events[0].is_set() is True


def test_sub_workflow_executor_timeout_signals_nested_cancel(monkeypatch):
    target = SimpleNamespace(id=5, uid="wf-target")
    parent = SimpleNamespace(id=1)
    nested_cancel_events = []

    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_uid", lambda uid: target if uid == "wf-target" else None)
    monkeypatch.setattr("executors.sub_workflow_executor.get_workflow_by_id", lambda workflow_id: parent if workflow_id == 1 else None)
    monkeypatch.setattr("executors.sub_workflow_executor.has_cross_workflow_cycle", lambda parent_id, target_uid: False)

    def workflow_runner(workflow_id, reason="manual", cancel_event=None):
        nested_cancel_events.append(cancel_event)
        if cancel_event is not None:
            cancel_event.wait(1.0)
        else:
            time.sleep(0.5)
        return False

    result = SubWorkflowExecutor().execute(
        script_path="wf-target",
        workflow_id=1,
        timeout=0.05,
        workflow_runner=workflow_runner,
    )

    assert result.success is False
    assert "超时" in (result.error_message or "")
    assert nested_cancel_events
    assert nested_cancel_events[0] is not None
    assert nested_cancel_events[0].is_set() is True


def test_engine_maps_executor_cancellation_to_cancelled_step(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=2,
            uid="step-powerbi",
            order=1,
            name="Power BI",
            step_type="powerbi_refresh",
            script_path="demo.pbix",
            cwd="",
            chart_theme="",
            timeout_seconds=30,
            retry_count=0,
            get_args=lambda: [],
            workflow_id=1,
        )
        step_log = SimpleNamespace(id=301)
        captured = {}

        class CancelledExecutor:
            def execute(self, **kwargs):
                kwargs["cancel_event"].set()
                engine._cancelled = True
                return ExecutorResult(
                    success=False,
                    exit_code=-1,
                    start_time=None,
                    end_time=None,
                    error_message="用户取消",
                )

        def fake_finish_step(current_step, step_log_id, result, exec_result=None, signal_policy=None):
            captured["result"] = result

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine.get_executor", lambda step_type: CancelledExecutor())
        monkeypatch.setattr(engine, "_finish_step", fake_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)
        engine._cancelled = False

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert result.status == "cancelled"
        assert result.exit_code == -1
        assert captured["result"].status == "cancelled"
    finally:
        engine.shutdown(wait=False)


def test_execute_parallel_steps_cleans_up_worker_sessions(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(max_workers=2)
        steps = [
            SimpleNamespace(id=1, order=1, name="A"),
            SimpleNamespace(id=2, order=2, name="B"),
        ]
        cleanup_calls = []

        monkeypatch.setattr(
            "engine.cleanup_session",
            lambda: cleanup_calls.append(threading.get_ident()),
        )
        monkeypatch.setattr(
            engine,
            "_execute_single_step",
            lambda workflow, step, run_history_id, log_dir, signal_policy, prev_step_status_map=None, run_cancel_event=None: StepResult(
                step_id=step.id,
                step_name=step.name,
                status="success",
                exit_code=0,
            ),
        )

        results = engine._execute_parallel_steps(
            workflow,
            steps,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(),
        )

        assert [result.step_id for result in results] == [1, 2]
        assert len(cleanup_calls) == 2
    finally:
        engine.shutdown(wait=False)


def test_execute_parallel_steps_stops_submitting_after_cancel(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(max_workers=1)
        steps = [
            SimpleNamespace(id=1, order=1, name="A"),
            SimpleNamespace(id=2, order=2, name="B"),
            SimpleNamespace(id=3, order=3, name="C"),
        ]
        calls = []

        def fake_execute_single_step(
            workflow,
            step,
            run_history_id,
            log_dir,
            signal_policy,
            prev_step_status_map=None,
            run_cancel_event=None,
        ):
            calls.append(step.id)
            engine.cancel()
            return StepResult(
                step_id=step.id,
                step_name=step.name,
                status="cancelled",
                exit_code=-1,
            )

        monkeypatch.setattr("engine.cleanup_session", lambda: None)
        monkeypatch.setattr(engine, "_execute_single_step", fake_execute_single_step)

        results = engine._execute_parallel_steps(
            workflow,
            steps,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(),
        )

        assert calls == [1]
        assert [result.step_id for result in results] == [1]
        assert results[0].status == "cancelled"
    finally:
        engine.shutdown(wait=False)


def test_finish_step_logs_duration_and_emits_it(monkeypatch):
    engine = WorkflowEngine()
    try:
        step = SimpleNamespace(id=7, name="步骤A", order=0)
        result = StepResult(
            step_id=7,
            step_name="步骤A",
            status="success",
            exit_code=0,
            start_time=datetime(2026, 1, 1, 10, 0, 0),
            end_time=datetime(2026, 1, 1, 10, 1, 23),
        )
        logs = []
        emitted = []

        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: logs.append(message))
        engine.step_finished.connect(lambda step_id, step_name, status, duration: emitted.append((step_id, step_name, status, duration)))

        engine._finish_step(
            step=step,
            step_log_id=99,
            result=result,
            signal_policy=SimpleNamespace(emit_step_signals=True),
        )

        assert logs == ["步骤 [0] 步骤A 成功 · 耗时 1m23s"]
        assert emitted == [(7, "步骤A", "success", 83.0)]
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_marks_log_failed_when_execution_chain_crashes(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=2,
            uid="step-crash",
            order=1,
            name="Crash",
            step_type="python",
        )
        step_log = SimpleNamespace(id=501)
        updates = []

        def fake_update_step_log(step_log_id, **kwargs):
            updates.append((step_log_id, kwargs))

        def fail_finish_step(*args, **kwargs):
            raise RuntimeError("finish failed")

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", fake_update_step_log)
        monkeypatch.setattr("engine.get_executor", lambda step_type: object())
        monkeypatch.setattr(
            engine,
            "_execute_step_with_retries",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("executor chain crashed")),
        )
        monkeypatch.setattr(engine, "_finish_step", fail_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert result.status == "failure"
        assert result.exit_code == 1
        assert "executor chain crashed" in result.error_message
        assert updates[0] == (501, {"status": "running", "start_time": updates[0][1]["start_time"]})
        assert updates[-1][0] == 501
        assert updates[-1][1]["status"] == "failure"
        assert updates[-1][1]["exit_code"] == 1
        assert "executor chain crashed" in updates[-1][1]["error_message"]
        assert "finish failed" in updates[-1][1]["error_message"]
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_marks_log_failed_when_running_mark_crashes(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=3,
            uid="step-start-crash",
            order=1,
            name="Start Crash",
            step_type="python",
        )
        step_log = SimpleNamespace(id=502)
        updates = []

        def fake_update_step_log(step_log_id, **kwargs):
            if kwargs.get("status") == "running":
                raise RuntimeError("running mark failed")
            updates.append((step_log_id, kwargs))

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", fake_update_step_log)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert result.status == "failure"
        assert result.exit_code == 1
        assert "running mark failed" in result.error_message
        assert updates[-1][0] == 502
        assert updates[-1][1]["status"] == "failure"
        assert "running mark failed" in updates[-1][1]["error_message"]
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_does_not_retry_manual_required_background_risk(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=4,
            uid="step-powerbi-manual",
            order=1,
            name="Power BI Manual",
            step_type="powerbi_refresh",
            script_path="demo.pbix",
            cwd="",
            chart_theme="",
            timeout_seconds=30,
            retry_count=2,
            get_args=lambda: ["--no-auto-close"],
        )
        step_log = SimpleNamespace(id=503)
        attempts = []
        finished = []

        class ManualRiskExecutor:
            def execute(self, **kwargs):
                attempts.append(kwargs)
                return ExecutorResult(
                    success=False,
                    exit_code=2,
                    error_message="Power BI 未自动关闭，当前步骤无法确认刷新完成",
                    extra=build_policy_extra(
                        manual_required=True,
                        background_risk=True,
                    ),
                )

        def fake_finish_step(current_step, step_log_id, result, exec_result=None, signal_policy=None):
            finished.append((current_step, step_log_id, result, exec_result))

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine.get_executor", lambda step_type: ManualRiskExecutor())
        monkeypatch.setattr(engine, "_finish_step", fake_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert len(attempts) == 1
        assert result.status == "failure"
        assert result.exit_code == 2
        assert "未自动关闭" in result.error_message
        assert finished[-1][2].status == "failure"
        assert finished[-1][3].extra[ResultPolicyKeys.BACKGROUND_RISK] is True
    finally:
        engine.shutdown(wait=False)


def test_execute_single_step_does_not_retry_manual_required_without_background_risk(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=5,
            uid="step-powerbi-no-auto-refresh",
            order=1,
            name="Power BI Manual Refresh",
            step_type="powerbi_refresh",
            script_path="demo.pbix",
            cwd="",
            chart_theme="",
            timeout_seconds=30,
            retry_count=2,
            get_args=lambda: ["--no-auto-refresh"],
        )
        step_log = SimpleNamespace(id=504)
        attempts = []
        finished = []

        class ManualRequiredExecutor:
            def execute(self, **kwargs):
                attempts.append(kwargs)
                return ExecutorResult(
                    success=False,
                    exit_code=2,
                    error_message="Power BI 需要人工刷新确认，当前步骤未自动确认成功",
                    extra=build_policy_extra(manual_required=True),
                )

        def fake_finish_step(current_step, step_log_id, result, exec_result=None, signal_policy=None):
            finished.append((current_step, step_log_id, result, exec_result))

        monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: step_log)
        monkeypatch.setattr("engine.update_step_log", lambda *args, **kwargs: None)
        monkeypatch.setattr("engine.get_executor", lambda step_type: ManualRequiredExecutor())
        monkeypatch.setattr(engine, "_finish_step", fake_finish_step)
        monkeypatch.setattr(engine, "_emit_log", lambda message: None)

        result = engine._execute_single_step(
            workflow,
            step,
            run_history_id=11,
            log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )

        assert len(attempts) == 1
        assert result.status == "failure"
        assert result.exit_code == 2
        assert "人工刷新确认" in result.error_message
        assert finished[-1][2].status == "failure"
        assert finished[-1][3].extra == build_policy_extra(manual_required=True)
    finally:
        engine.shutdown(wait=False)
