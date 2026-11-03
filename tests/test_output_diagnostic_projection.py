# -*- coding: utf-8 -*-
"""Executor policy diagnostics survive real step execution and final persistence."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from engine import WorkflowEngine
from executors.base import ExecutorResult
from executors.result_policy import build_policy_extra


OUTPUT_WARNING = "输出采集不完整：stderr reader 尚未退出"


@pytest.fixture
def run_step(monkeypatch, tmp_path):
    engine = WorkflowEngine()
    workflow = SimpleNamespace(id=1, chart_theme="default")
    step = SimpleNamespace(
        id=2, uid="step-output-risk", order=1, name="输出风险",
        step_type="python", script_path="demo.py", cwd="", chart_theme="",
        timeout_seconds=30, retry_count=2, get_args=lambda: [], workflow_id=1,
    )
    created = []
    updates = []
    attempts = []
    lookups = []

    def create_step_log(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(id=301)

    monkeypatch.setattr("engine.create_step_log", create_step_log)
    monkeypatch.setattr(
        "engine.update_step_log",
        lambda step_log_id, **kwargs: updates.append((step_log_id, kwargs)),
    )
    monkeypatch.setattr(engine, "_emit_log", lambda message: None)

    def run(exec_result, *, cancelled=False):
        class OutputExecutor:
            def execute(self, **kwargs):
                attempts.append(kwargs)
                if cancelled:
                    kwargs["cancel_event"].set()
                return exec_result

        def get_executor(step_type):
            lookups.append(step_type)
            return OutputExecutor()

        monkeypatch.setattr("engine.get_executor", get_executor)
        result = engine._execute_single_step(
            workflow, step, run_history_id=11, log_dir=tmp_path,
            signal_policy=SimpleNamespace(emit_step_signals=False),
        )
        return SimpleNamespace(
            result=result, created=created, updates=updates,
            attempts=attempts, lookups=lookups,
        )

    try:
        yield run
    finally:
        engine.shutdown(wait=False)


def assert_terminal_write(captured, status):
    assert captured.created == [{"run_history_id": 11, "step_id": 2, "order": 1}]
    assert captured.lookups == ["python"]
    assert len(captured.attempts) == 1
    assert [step_log_id for step_log_id, _ in captured.updates] == [301, 301]
    assert captured.updates[0][1]["status"] == "running"
    assert captured.result.status == status
    assert captured.updates[-1][1]["status"] == status
    assert captured.updates[-1][1]["error_message"] == captured.result.error_message


@pytest.mark.parametrize(
    ("extra", "expected_notes"),
    [
        (build_policy_extra(manual_required=True, non_retryable=True), ("需要人工确认",)),
        (
            build_policy_extra(manual_required=True, non_retryable=True, background_risk=True),
            ("需要人工确认", "可能仍有后台任务运行"),
        ),
        (build_policy_extra(background_risk=True), ("可能仍有后台任务运行",)),
        (build_policy_extra(orphan_risk=True), ("子工作流可能仍在后台运行",)),
        (build_policy_extra(non_retryable=True), ()),
    ],
    ids=["manual", "manual-background", "background", "orphan", "non-retryable"],
)
def test_success_with_policy_persists_output_warning_without_retry(run_step, extra, expected_notes):
    start_time = datetime(2026, 10, 30, 10, 0, 0)
    end_time = datetime(2026, 10, 30, 10, 0, 1)
    captured = run_step(ExecutorResult(
        success=True, exit_code=0, start_time=start_time, end_time=end_time,
        stdout_path="stdout.txt", stderr_path="stderr.txt",
        error_message=OUTPUT_WARNING, extra=extra,
    ))

    assert_terminal_write(captured, "success")
    assert captured.result.exit_code == 0
    assert captured.result.start_time == start_time
    assert captured.result.end_time == end_time
    terminal = captured.updates[-1][1]
    assert terminal["exit_code"] == 0
    assert terminal["stdout_path"] == "stdout.txt"
    assert terminal["stderr_path"] == "stderr.txt"
    assert OUTPUT_WARNING in terminal["error_message"]
    for note in expected_notes:
        assert note in terminal["error_message"]


def test_success_with_risk_without_detail_still_persists_policy_note(run_step):
    captured = run_step(ExecutorResult(
        success=True, exit_code=0,
        extra=build_policy_extra(manual_required=True, background_risk=True),
    ))

    assert_terminal_write(captured, "success")
    assert captured.updates[-1][1]["error_message"] == (
        "执行诊断: 需要人工确认；可能仍有后台任务运行"
    )


@pytest.mark.parametrize(
    "extra",
    [
        {},
        build_policy_extra(note=OUTPUT_WARNING),
        build_policy_extra(
            manual_required=False, background_risk=False, orphan_risk=False, non_retryable=False,
        ),
        {"capture_warning": True},
    ],
    ids=["empty", "note-only", "false-policy", "unknown-policy"],
)
def test_ordinary_success_does_not_project_arbitrary_error_text(run_step, extra):
    captured = run_step(ExecutorResult(
        success=True, exit_code=0, error_message="executor informational detail", extra=extra,
    ))

    assert_terminal_write(captured, "success")
    assert captured.result.exit_code == 0
    assert captured.result.error_message is None
    assert captured.updates[-1][1]["error_message"] is None


@pytest.mark.parametrize("status", ["failure", "cancelled"])
def test_incomplete_output_failure_or_cancel_preserves_policy_without_retry(run_step, status):
    cancelled = status == "cancelled"
    exit_code = -1 if cancelled else 1
    captured = run_step(
        ExecutorResult(
            success=False, exit_code=exit_code, error_message=OUTPUT_WARNING,
            extra=build_policy_extra(
                cancelled=cancelled, manual_required=True, background_risk=True, non_retryable=True,
            ),
        ),
        cancelled=cancelled,
    )

    assert_terminal_write(captured, status)
    assert captured.result.exit_code == exit_code
    terminal_message = captured.updates[-1][1]["error_message"]
    assert OUTPUT_WARNING in terminal_message
    assert "需要人工确认" in terminal_message
    assert "可能仍有后台任务运行" in terminal_message
    if cancelled:
        assert terminal_message.startswith("用户取消")
