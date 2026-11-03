# -*- coding: utf-8 -*-
"""工作流运行模式的步骤筛选逻辑。"""

from __future__ import annotations

from typing import Callable, Iterable, List

from exceptions import ConfigurationError
from engine_core.stage_selection import _select_only_stage, _select_from_stage

MODE_FULL = "full"
MODE_FROM_STEP = "from_step"
MODE_ONLY_STEP = "only_step"
MODE_ONLY_STAGE = "only_stage"
MODE_FROM_STAGE = "from_stage"
MODE_RETRY_FAILED = "retry_failed"
MODE_STEP_RANGE = "step_range"


def select_steps(
    *,
    all_steps: List[object],
    mode_value: str,
    step_id: int | None,
    workflow,
    stage_uid: str | None = None,
    get_stage_order_map: Callable[[int], dict],
    get_latest_run_history: Callable[..., object | None],
    get_step_logs_by_run: Callable[[int], Iterable[object]],
    running_status_value: str,
    pending_status_value: str,
    log_cb: Callable[[str], None] | None = None,
    end_step_id: int | None = None,
) -> List[object]:
    """根据运行模式筛选待执行步骤。

    注意：single_script_enabled 已退役，本函数按步骤表正常选择，
    忽略该字段（旧库 single_script_enabled=1 的工作流按普通工作流处理）。
    """
    if mode_value == MODE_FULL:
        return all_steps
    if mode_value == MODE_FROM_STEP:
        return _select_from_step(all_steps, step_id)
    if mode_value == MODE_STEP_RANGE:
        return _select_step_range(all_steps, step_id, end_step_id, log_cb=log_cb)
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
    raise ConfigurationError(f"未知的运行模式: {mode_value}")


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


def _select_step_range(
    all_steps: List[object],
    start_step_id: int | None,
    end_step_id: int | None,
    *,
    log_cb: Callable[[str], None] | None = None,
) -> List[object]:
    """按全局步骤顺序选取 [起点, 终点]（含两端，可跨阶段）。

    与 from_step 一致：不按步骤属性做额外过滤（如 skip_on_success 仍交由执行期处理）。
    起点位于终点之后时自动交换并通过 log_cb 说明。
    """
    index_by_id = {step.id: idx for idx, step in enumerate(all_steps)}
    if start_step_id not in index_by_id:
        raise ConfigurationError(f"未找到步骤: {start_step_id}")
    if end_step_id not in index_by_id:
        raise ConfigurationError(f"未找到步骤: {end_step_id}")
    start_idx = index_by_id[start_step_id]
    end_idx = index_by_id[end_step_id]
    if start_idx > end_idx:
        start_idx, end_idx = end_idx, start_idx
        if log_cb:
            log_cb("区间起点位于终点之后，已自动交换起点与终点")
    return list(all_steps[start_idx:end_idx + 1])


def _select_only_step(all_steps: List[object], step_id: int | None) -> List[object]:
    for step in all_steps:
        if step.id == step_id:
            return [step]
    raise ConfigurationError(f"未找到步骤: {step_id}")


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
