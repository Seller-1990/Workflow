from __future__ import annotations
"""Batch-result attribution, progress and failure diagnostic projection."""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine import RunSignalPolicy, StepResult, WorkflowEngine
    from models import Step


def append_failed_detail(
    engine: WorkflowEngine,
    failed_details: list[dict],
    step: Step,
    result: StepResult,
) -> None:
    failed_details.append({
        "step_id": step.id,
        "step_name": step.name,
        "error_message": result.error_message or "未知错误",
        "suggested_fix": result.suggested_fix or "",
    })


def emit_failed_details(
    engine: WorkflowEngine,
    failed_details: list[dict],
    signal_policy: RunSignalPolicy,
) -> None:
    if failed_details and signal_policy.emit_error_details:
        engine.error_details.emit(failed_details)


def update_execution_progress(
    engine: WorkflowEngine,
    completed_steps: int,
    total_steps: int,
    signal_policy: RunSignalPolicy,
) -> None:
    if signal_policy.emit_progress_signals:
        engine.progress_updated.emit(completed_steps, total_steps)


def handle_batch_results(
    engine: WorkflowEngine,
    batch: list[Step],
    results: list[StepResult],
    failed_details: list[dict],
    signal_policy: RunSignalPolicy,
) -> bool:
    has_failure = False
    # F-15: 按 step_id 配对，不依赖位置——scheduler 按步骤 order 排序结果，
    # 同批出现重复 order 时（数据异常边缘态）排序稳定性不保证与 batch 一致，
    # 位置 zip 会把失败详情归因到错误步骤。StepResult 与 _CancelledResult
    # 均携带 step_id；缺 step_id 的异常结果回退位置配对。
    results_by_id: dict = {}
    positional_results: list = []
    for r in results:
        sid = getattr(r, "step_id", None)
        if sid is None:
            positional_results.append(r)
        else:
            results_by_id[sid] = r
    paired: dict = {}
    used_positional = 0
    for step in batch:
        if step.id in results_by_id:
            paired[step.id] = results_by_id.pop(step.id)
        elif used_positional < len(positional_results):
            paired[step.id] = positional_results[used_positional]
            used_positional += 1
    leftovers = list(results_by_id.values()) + positional_results[used_positional:]

    for step in batch:
        result = paired.get(step.id)
        if result is None:
            # 没有结果对应此步骤（不应发生；scheduler 占位保证数量守恒）——
            # 归位 leftover，保底不错配
            if leftovers:
                result = leftovers.pop(0)
            else:
                continue
        if result.status == "cancelled":
            engine._emit_failed_details(failed_details, signal_policy)
            return False
        if not result.success:
            has_failure = True
            engine._append_failed_detail(failed_details, step, result)

    if has_failure:
        engine._emit_failed_details(failed_details, signal_policy)
        return False
    return True
