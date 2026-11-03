"""Stage-bound selection; step/range/history dispatch stays in selection."""
from __future__ import annotations

from typing import Callable, List

from exceptions import ConfigurationError


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
