"""Terminal step persistence and completion signal projection."""
from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from engine import RunSignalPolicy, StepResult, WorkflowEngine
    from executors import ExecutorResult
    from models import Step


def _engine_module():
    import engine
    return engine


def finish_step(
    engine: WorkflowEngine,
    step: Step,
    step_log_id: int,
    result: StepResult,
    exec_result: ExecutorResult = None,
    signal_policy: Optional[RunSignalPolicy] = None,
):
    """完成步骤处理"""
    eng = _engine_module()
    signal_policy = signal_policy or eng.RunSignalPolicy()
    # 更新步骤日志
    update_data = {
        "status": result.status,
        "exit_code": result.exit_code,
        "end_time": result.end_time or datetime.now(),
        "error_message": result.error_message
    }

    if exec_result:
        update_data["stdout_path"] = exec_result.stdout_path
        update_data["stderr_path"] = exec_result.stderr_path
    elif result.log_dir:
        # M2 修复：cancelled / failure 路径下若 exec_result 为 None，
        # 仍从 result.log_dir 推导出 stdout/stderr 路径，避免历史日志丢失
        from os.path import join, isfile
        stdout_guess = join(str(result.log_dir), "stdout.txt")
        stderr_guess = join(str(result.log_dir), "stderr.txt")
        if isfile(stdout_guess):
            update_data["stdout_path"] = stdout_guess
        if isfile(stderr_guess):
            update_data["stderr_path"] = stderr_guess

    eng.update_step_log(step_log_id, **update_data)

    # 发送信号
    status_text = {
        "success": "成功",
        "skipped": "已跳过",
        "cancelled": "已取消",
    }.get(result.status, "失败")
    duration_text = eng.format_duration_short(result.duration_seconds)
    suffix = f" · 耗时 {duration_text}" if duration_text else ""
    engine._emit_log(f"步骤 [{step.order}] {step.name} {status_text}{suffix}")
    if signal_policy.emit_step_signals:
        engine.step_finished.emit(step.id, step.name, result.status, result.duration_seconds)
