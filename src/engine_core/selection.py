# -*- coding: utf-8 -*-
"""工作流运行模式的步骤筛选逻辑。"""

from __future__ import annotations

from typing import Callable, Iterable, List

from exceptions import ConfigurationError

MODE_FULL = "full"
MODE_FROM_STEP = "from_step"
MODE_ONLY_STEP = "only_step"
MODE_ONLY_STAGE = "only_stage"
MODE_FROM_STAGE = "from_stage"
MODE_RETRY_FAILED = "retry_failed"


def select_steps(
    *,
    all_steps: List[object],
    mode_value: str,
    step_id: int | None,
    workflow,
    stage_uid: str | None = None,
    get_single_script_step: Callable[[object], object | None],
    get_stage_order_map: Callable[[int], dict],
    get_latest_run_history: Callable[..., object | None],
    get_step_logs_by_run: Callable[[int], Iterable[object]],
    running_status_value: str,
    pending_status_value: str,
    log_cb: Callable[[str], None] | None = None,
) -> List[object]:
    """根据运行模式筛选待执行步骤。"""
    if getattr(workflow, "single_script_enabled", False):
        return _select_single_script_step(
            workflow=workflow,
            mode_value=mode_value,
            step_id=step_id,
            get_single_script_step=get_single_script_step,
        )

    if mode_value == MODE_FULL:
        return all_steps
    if mode_value == MODE_FROM_STEP:
        return _select_from_step(all_steps, step_id)
    if mode_value == MODE_ONLY_STEP:
        return _select_only_step(all_steps, step_id)
    if mode_value == MODE_ONLY_STAGE:
        return _select_only_stage(all_steps, stage_uid)
    if mode_value == MODE_FROM_STAGE:
        return _select_from_stage(
            all_steps=all_steps,
            workflow_id=workflow.id,
            stage_uid=stage_uid,
            get_stage_order_map=get_stage_order_map,
        )
    if mode_value == MODE_RETRY_FAILED:
        return _select_retry_failed(
            all_steps=all_steps,
            workflow_id=workflow.id,
            get_latest_run_history=get_latest_run_history,
            get_step_logs_by_run=get_step_logs_by_run,
            running_status_value=running_status_value,
            pending_status_value=pending_status_value,
            log_cb=log_cb,
        )
    return all_steps


def _select_single_script_step(
    *,
    workflow,
    mode_value: str,
    step_id: int | None,
    get_single_script_step: Callable[[object], object | None],
) -> List[object]:
    step = get_single_script_step(workflow)
    if not step:
        raise ConfigurationError("单脚本模式未配置脚本路径")
    if mode_value in {MODE_FULL, MODE_RETRY_FAILED, MODE_ONLY_STAGE, MODE_FROM_STAGE}:
        return [step]
    if mode_value in {MODE_FROM_STEP, MODE_ONLY_STEP}:
        if step.id == step_id:
            return [step]
        raise ConfigurationError("单脚本模式仅支持运行单脚本步骤")
    return [step]


def _select_from_step(all_steps: List[object], step_id: int | None) -> List[object]:
    result = []
    found = False
    for step in all_steps:
        if step.id == step_id:
            found = True
        if found:
            result.append(step)
    if not result:
        raise ConfigurationError(f"未找到步骤: {step_id}")
    return result


def _select_only_step(all_steps: List[object], step_id: int | None) -> List[object]:
    for step in all_steps:
        if step.id == step_id:
            return [step]
    raise ConfigurationError(f"未找到步骤: {step_id}")


def _select_only_stage(all_steps: List[object], stage_uid: str | None) -> List[object]:
    if not stage_uid:
        raise ConfigurationError("ONLY_STAGE 模式需要指定 stage_uid")
    stage_steps = [step for step in all_steps if getattr(step, "stage_uid", None) == stage_uid]
    if not stage_steps:
        raise ConfigurationError(f"阶段 {stage_uid} 中没有步骤")
    return stage_steps


def _select_from_stage(
    *,
    all_steps: List[object],
    workflow_id: int,
    stage_uid: str | None,
    get_stage_order_map: Callable[[int], dict],
) -> List[object]:
    if not stage_uid:
        raise ConfigurationError("FROM_STAGE 模式需要指定 stage_uid")
    stage_map = get_stage_order_map(workflow_id)
    target_order = stage_map.get(stage_uid)
    if target_order is None:
        raise ConfigurationError(f"未找到阶段: {stage_uid}")

    result = []
    for step in all_steps:
        step_stage_uid = getattr(step, "stage_uid", None)
        step_order = stage_map.get(step_stage_uid, 0)
        if step_order >= target_order:
            result.append(step)
    if not result:
        raise ConfigurationError(f"阶段 {stage_uid} 及之后没有步骤")
    return result


def _select_retry_failed(
    *,
    all_steps: List[object],
    workflow_id: int,
    get_latest_run_history: Callable[..., object | None],
    get_step_logs_by_run: Callable[[int], Iterable[object]],
    running_status_value: str,
    pending_status_value: str,
    log_cb: Callable[[str], None] | None = None,
) -> List[object]:
    latest_run = get_latest_run_history(
        workflow_id,
        exclude_statuses=[running_status_value, pending_status_value],
        only_finished=True,
    )
    if not latest_run:
        raise ConfigurationError("没有历史运行记录")

    failed_step_ids = {
        log.step_id
        for log in get_step_logs_by_run(latest_run.id)
        if log.status == "failure"
    }
    if not failed_step_ids:
        if log_cb:
            log_cb("上次运行没有失败的步骤")
        return []
    return [step for step in all_steps if step.id in failed_step_ids]
