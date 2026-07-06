# -*- coding: utf-8 -*-
"""单步执行子系统（batch-3 自 engine.py 纯移动提取，行为不变）

覆盖「执行单个步骤的完整生命周期」：skip-on-success 判定、StepLog 创建、
running 标记、执行尝试与重试、取消收尾、失败诊断、并行批执行与统一收尾。

设计要点（与 ui/run_dispatch.py 批次一/二同一约定）：
- 每个函数的首个参数 ``engine`` 即 WorkflowEngine 实例；跨方法调用一律走
  ``engine._xxx`` 委托方法，保持实例级 monkeypatch（测试替身）动态分发语义。
- ``StepResult`` / ``RunStatus`` / ``RunSignalPolicy`` 定义在 engine.py，
  顶层 ``import engine`` 会形成循环导入；统一经 ``_engine_module()``
  在调用时延迟解析。
- ``create_step_log`` / ``update_step_log`` / ``get_executor`` /
  ``cleanup_session`` / ``has_non_retryable_policy`` / ``ErrorDiagnostician`` /
  ``format_duration_short`` / ``_install_cancel_watcher`` / ``_run_steps_parallel``
  / ``_should_skip_on_success`` / ``_record_skip_on_success`` 等依赖同样经
  engine 模块全局延迟解析（late-bound），保持
  ``monkeypatch.setattr("engine.xxx", ...)`` 模块级补丁语义不变。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from run_policy_notes import append_policy_risk_note

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from engine import RunSignalPolicy, StepResult, WorkflowEngine
    from executors import ExecutorResult
    from models import Step, Workflow


def _engine_module():
    """延迟导入 engine 模块（避免顶层循环导入，并保留 engine.* 模块级 monkeypatch 语义）"""
    import engine

    return engine


def execute_skip_on_success_if_needed(
    engine: WorkflowEngine,
    step: Step,
    run_history_id: int,
    signal_policy: RunSignalPolicy,
    prev_step_status_map: Optional[dict] = None,
) -> Optional[StepResult]:
    """Return a skipped result when check_skip_on_success is already satisfied."""
    eng = _engine_module()
    if not eng._should_skip_on_success(
        step=step,
        run_history_id=run_history_id,
        running_status_value=eng.RunStatus.RUNNING.value,
        pending_status_value=eng.RunStatus.PENDING.value,
        prev_step_status_map=prev_step_status_map,
    ):
        return None

    engine._emit_log(f"跳过步骤 [{step.order}] {step.name}（上次已成功）")
    if signal_policy.emit_step_signals:
        engine.step_started.emit(step.id, step.name)

    # StepLog must be written after step_started so synchronous listeners do
    # not observe a skipped row before the step has semantically started.
    skip_decision = eng._record_skip_on_success(step=step, run_history_id=run_history_id)
    result = eng.StepResult(
        step_id=step.id,
        step_name=step.name,
        status="skipped",
        exit_code=0,
        start_time=skip_decision.start_time,
        end_time=skip_decision.end_time,
        error_message=skip_decision.note,
    )
    if signal_policy.emit_step_signals:
        engine.step_finished.emit(step.id, step.name, result.status, result.duration_seconds)
    return result


def begin_step_execution(
    engine: WorkflowEngine,
    step: Step,
    run_history_id: int,
    log_dir: Path,
) -> tuple[int, Path]:
    eng = _engine_module()
    step_log_dir = log_dir / f"step_{step.order:02d}_{step.uid}"
    step_log_dir.mkdir(parents=True, exist_ok=True)
    step_log = eng.create_step_log(
        run_history_id=run_history_id,
        step_id=step.id,
        order=step.order,
    )
    return step_log.id, step_log_dir


def mark_step_running(
    engine: WorkflowEngine,
    step: Step,
    step_log_id: int,
    signal_policy: RunSignalPolicy,
) -> None:
    eng = _engine_module()
    if signal_policy.emit_step_signals:
        engine.step_started.emit(step.id, step.name)
    engine._emit_log(f"开始步骤 [{step.order}] {step.name}")
    eng.update_step_log(step_log_id, status="running", start_time=datetime.now())


def cancelled_step_result(
    engine: WorkflowEngine,
    step: Step,
    exec_result: Optional[ExecutorResult] = None,
    step_log_dir: Optional[Path] = None,
) -> StepResult:
    eng = _engine_module()
    if exec_result is None:
        return eng.StepResult(
            step_id=step.id,
            step_name=step.name,
            status="cancelled",
            exit_code=-1,
            error_message="用户取消",
        )

    return eng.StepResult(
        step_id=step.id,
        step_name=step.name,
        status="cancelled",
        exit_code=exec_result.exit_code if exec_result.exit_code not in (None, 0) else -1,
        start_time=exec_result.start_time,
        end_time=exec_result.end_time,
        error_message="用户取消",
        log_dir=str(step_log_dir) if step_log_dir else None,
    )


def finish_cancelled_step(
    engine: WorkflowEngine,
    step: Step,
    step_log_id: int,
    signal_policy: RunSignalPolicy,
    exec_result: Optional[ExecutorResult] = None,
    step_log_dir: Optional[Path] = None,
) -> StepResult:
    result = engine._cancelled_step_result(step, exec_result, step_log_dir)
    engine._finish_step(step, step_log_id, result, exec_result, signal_policy)
    return result


def wait_before_retry(
    engine: WorkflowEngine,
    step: Step,
    attempt: int,
    cancel_event: threading.Event,
) -> bool:
    if attempt <= 0:
        return False

    delay = min(2 ** attempt, 60)
    engine._emit_log(f"第 {attempt + 1} 次重试，等待 {delay} 秒...")
    if not cancel_event.wait(delay):
        return False

    engine._emit_log(f"步骤 [{step.order}] {step.name} 重试等待期间已取消")
    return True


def execute_step_attempt(
    engine: WorkflowEngine,
    workflow: Workflow,
    step: Step,
    executor,
    step_log_id: int,
    step_log_dir: Path,
    cancel_event: threading.Event,
    run_cancel_event: threading.Event,
    signal_policy: RunSignalPolicy,
) -> tuple[Optional[StepResult], Optional[str]]:
    eng = _engine_module()
    try:
        exec_result = executor.execute(
            script_path=step.script_path,
            args=step.get_args(),
            cwd=step.cwd,
            log_dir=step_log_dir,
            timeout=step.timeout_seconds,
            chart_theme=step.chart_theme or workflow.chart_theme,
            workflow_id=workflow.id,
            workflow_runner=engine.run_sub_workflow,
            cancel_event=cancel_event,
        )

        if engine._is_run_cancelled(run_cancel_event) or cancel_event.is_set():
            engine._emit_log(f"步骤 [{step.order}] {step.name} 已取消")
            result = engine._finish_cancelled_step(
                step,
                step_log_id,
                signal_policy,
                exec_result=exec_result,
                step_log_dir=step_log_dir,
            )
            return result, None

        if exec_result.success:
            result = eng.StepResult(
                step_id=step.id,
                step_name=step.name,
                status="success",
                exit_code=exec_result.exit_code,
                start_time=exec_result.start_time,
                end_time=exec_result.end_time,
                log_dir=str(step_log_dir),
            )
            engine._finish_step(step, step_log_id, result, exec_result, signal_policy)
            return result, None

        if engine._is_non_retryable_executor_result(exec_result):
            result = eng.StepResult(
                step_id=step.id,
                step_name=step.name,
                status="failure",
                exit_code=exec_result.exit_code if exec_result.exit_code is not None else 1,
                start_time=exec_result.start_time,
                end_time=exec_result.end_time,
                error_message=append_policy_risk_note(exec_result.error_message, exec_result.extra),
                log_dir=str(step_log_dir),
            )
            engine._finish_step(step, step_log_id, result, exec_result, signal_policy)
            return result, None

        return None, exec_result.error_message
    except Exception as e:
        logger.warning("步骤执行异常: %s", e)
        return None, str(e)


def is_non_retryable_executor_result(exec_result: ExecutorResult) -> bool:
    eng = _engine_module()
    extra = getattr(exec_result, "extra", None) or {}
    return eng.has_non_retryable_policy(extra)


def build_failed_step_result(
    engine: WorkflowEngine,
    workflow: Workflow,
    step: Step,
    last_error: Optional[str],
    step_log_dir: Path,
) -> StepResult:
    eng = _engine_module()
    diagnosis = eng.ErrorDiagnostician.diagnose(
        error_message=last_error,
        step_type=step.step_type,
        context={"timeout": step.timeout_seconds, "script_path": step.script_path},
    )
    return eng.StepResult(
        step_id=step.id,
        step_name=step.name,
        status="failure",
        exit_code=1,
        error_message=last_error,
        log_dir=str(step_log_dir),
        suggested_fix=diagnosis["suggested_fix"],
    )


def build_unexpected_step_failure(
    engine: WorkflowEngine,
    step: Step,
    error: Exception,
    step_log_dir: Path,
) -> StepResult:
    eng = _engine_module()
    message = str(error) or error.__class__.__name__
    return eng.StepResult(
        step_id=step.id,
        step_name=step.name,
        status="failure",
        exit_code=1,
        end_time=datetime.now(),
        error_message=f"步骤执行异常: {message}",
        log_dir=str(step_log_dir),
    )


def finish_failed_step_after_unexpected_error(
    engine: WorkflowEngine,
    step: Step,
    step_log_id: int,
    result: StepResult,
    signal_policy: RunSignalPolicy,
) -> None:
    eng = _engine_module()
    try:
        engine._finish_step(step, step_log_id, result, signal_policy=signal_policy)
        return
    except Exception as finish_error:
        finish_error_message = str(finish_error) or finish_error.__class__.__name__
        logger.exception(
            "步骤异常收尾失败: step_id=%s order=%s",
            getattr(step, "id", None),
            getattr(step, "order", None),
        )

    error_message = result.error_message or "步骤执行异常"
    try:
        eng.update_step_log(
            step_log_id,
            status="failure",
            exit_code=1,
            end_time=result.end_time or datetime.now(),
            error_message=f"{error_message}; 收尾失败: {finish_error_message}",
        )
    except Exception:
        logger.exception(
            "步骤日志最小失败状态写入失败: step_log_id=%s step_id=%s",
            step_log_id,
            getattr(step, "id", None),
        )


def stop_cancel_watcher(engine: WorkflowEngine, cancel_watcher, step: Step) -> None:
    cancel_watcher.join(timeout=1)
    if cancel_watcher.is_alive():
        logger.warning(
            "cancel_watcher join 超时未退出: step_id=%s order=%s",
            getattr(step, "id", None),
            getattr(step, "order", None),
        )


def execute_step_with_retries(
    engine: WorkflowEngine,
    workflow: Workflow,
    step: Step,
    executor,
    step_log_id: int,
    step_log_dir: Path,
    signal_policy: RunSignalPolicy,
    run_cancel_event: threading.Event = None,
) -> StepResult:
    eng = _engine_module()
    max_retries = step.retry_count + 1
    last_error = None
    cancel_event = threading.Event()
    cancel_watcher = eng._install_cancel_watcher(
        lambda: engine._is_run_cancelled(run_cancel_event),
        cancel_event,
        poll_interval=0.2,
    )

    try:
        for attempt in range(max_retries):
            if engine._is_run_cancelled(run_cancel_event):
                engine._emit_log(f"步骤 [{step.order}] {step.name} 已取消")
                return engine._finish_cancelled_step(step, step_log_id, signal_policy)

            if engine._wait_before_retry(step, attempt, cancel_event):
                return engine._finish_cancelled_step(step, step_log_id, signal_policy)

            result, attempt_error = engine._execute_step_attempt(
                workflow=workflow,
                step=step,
                executor=executor,
                step_log_id=step_log_id,
                step_log_dir=step_log_dir,
                cancel_event=cancel_event,
                run_cancel_event=run_cancel_event,
                signal_policy=signal_policy,
            )
            if result is not None:
                return result
            last_error = attempt_error

        result = engine._build_failed_step_result(
            workflow,
            step,
            last_error,
            step_log_dir,
        )
        engine._finish_step(step, step_log_id, result, signal_policy=signal_policy)
        return result
    finally:
        cancel_event.set()
        engine._stop_cancel_watcher(cancel_watcher, step)


def execute_single_step(
    engine: WorkflowEngine,
    workflow: Workflow,
    step: Step,
    run_history_id: int,
    log_dir: Path,
    signal_policy: RunSignalPolicy,
    prev_step_status_map: Optional[dict] = None,
    run_cancel_event: threading.Event = None,
) -> StepResult:
    """执行单个步骤（带重试）"""
    eng = _engine_module()
    # R2-#1: prev_step_status_map 来自 _execute_steps 的 local，避免父子工作流共享 self 属性互相覆盖
    skipped_result = engine._execute_skip_on_success_if_needed(
        step,
        run_history_id,
        signal_policy,
        prev_step_status_map=prev_step_status_map,
    )
    if skipped_result is not None:
        return skipped_result

    step_log_id = None
    step_log_dir = None
    try:
        step_log_id, step_log_dir = engine._begin_step_execution(step, run_history_id, log_dir)
        engine._mark_step_running(step, step_log_id, signal_policy)
        try:
            executor = eng.get_executor(step.step_type)
        except ValueError as e:
            result = eng.StepResult(
                step_id=step.id,
                step_name=step.name,
                status="failure",
                exit_code=1,
                error_message=str(e),
                log_dir=str(step_log_dir),
            )
            engine._finish_step(step, step_log_id, result, signal_policy=signal_policy)
            return result

        return engine._execute_step_with_retries(
            workflow=workflow,
            step=step,
            executor=executor,
            step_log_id=step_log_id,
            step_log_dir=step_log_dir,
            signal_policy=signal_policy,
            run_cancel_event=run_cancel_event,
        )
    except Exception as e:
        logger.exception(
            "步骤执行链路异常: step_id=%s order=%s",
            getattr(step, "id", None),
            getattr(step, "order", None),
        )
        if step_log_id is None or step_log_dir is None:
            raise
        result = engine._build_unexpected_step_failure(step, e, step_log_dir)
        engine._finish_failed_step_after_unexpected_error(
            step,
            step_log_id,
            result,
            signal_policy,
        )
        return result


def execute_parallel_steps(
    engine: WorkflowEngine,
    workflow: Workflow,
    steps: List[Step],
    run_history_id: int,
    log_dir: Path,
    signal_policy: RunSignalPolicy,
    prev_step_status_map: Optional[dict] = None,
    run_cancel_event: threading.Event = None,
) -> List[StepResult]:
    """并行执行多个步骤（Fan-Out/Fan-In 模式）

    CA2: 调度逻辑下沉到 engine_core.scheduler.run_steps_parallel
    MA2: 尊重 workflow.max_workers，避免独占资源的步骤一窝蜂打入
    R2-#1: prev_step_status_map 由 caller 透传，避免 self 属性被并行/嵌套覆盖
    """
    eng = _engine_module()
    max_workers = max(1, int(getattr(workflow, "max_workers", 0) or 1))

    def _step_runner(step):
        try:
            return engine._execute_single_step(
                workflow, step, run_history_id, log_dir, signal_policy,
                prev_step_status_map=prev_step_status_map,
                run_cancel_event=run_cancel_event,
            )
        finally:
            eng.cleanup_session()

    def _on_exception(step, e):
        return eng.StepResult(
            step_id=step.id,
            step_name=step.name,
            status="failure",
            exit_code=1,
            error_message=str(e),
        )

    metrics = eng.SchedulerMetrics()
    results = eng._run_steps_parallel(
        steps,
        executor=engine._executor,
        max_workers=max_workers,
        step_runner=_step_runner,
        on_exception=_on_exception,
        should_stop=lambda: engine._is_run_cancelled(run_cancel_event),
        metrics=metrics,
    )
    engine._last_scheduler_metrics = metrics
    return results


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
