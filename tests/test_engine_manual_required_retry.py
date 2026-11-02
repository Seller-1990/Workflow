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


def test_execute_single_step_does_not_retry_manual_required_without_background_risk(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(id=1, chart_theme="default")
        step = SimpleNamespace(
            id=5,
            uid="step-powerbi-no-auto-refresh",
            order=1,
            name="Power BI Manual Refresh",
            step_type="bat",
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
