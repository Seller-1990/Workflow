# -*- coding: utf-8 -*-
"""Stage and step ordering mutation service."""

from __future__ import annotations

from typing import Iterable

from database import get_session, get_stage_order_map, get_steps_by_workflow
from engine_core.batch import compute_batches
from exceptions import WorkflowError
from models import Step, Workflow, WorkflowStage


def _stage_sorted_steps(workflow_id: int) -> list[Step]:
    steps = get_steps_by_workflow(workflow_id)
    stage_map = get_stage_order_map(workflow_id)
    return sorted(
        steps,
        key=lambda step: (int(stage_map.get(getattr(step, "stage_uid", None), 0) or 0), step.order),
    )


def _validate_workflow_plan(session, workflow_id: int) -> None:
    workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        raise WorkflowError("工作流不存在")

    steps = session.query(Step).filter(Step.workflow_id == workflow_id).all()
    stages = (
        session.query(WorkflowStage)
        .filter(WorkflowStage.workflow_id == workflow_id)
        .order_by(WorkflowStage.order.asc())
        .all()
    )
    stage_map = {stage.uid: int(stage.order or 0) for stage in stages}
    compute_batches(workflow, steps, stage_map)


def apply_orders_and_stage_updates(
    workflow_id: int,
    stage_overrides: dict[int, str] | None,
    step_ids_in_order: Iterable[int],
) -> bool:
    """Apply step order and stage changes in one transaction."""
    if not workflow_id:
        return False

    with get_session() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            raise WorkflowError("工作流不存在")

        steps = session.query(Step).filter(Step.workflow_id == workflow_id).all()
        steps_by_id = {step.id: step for step in steps}

        for index, step_id in enumerate(step_ids_in_order):
            step = steps_by_id.get(int(step_id))
            if step:
                step.order = index

        for step_id, stage_uid in (stage_overrides or {}).items():
            step = steps_by_id.get(int(step_id))
            if step:
                step.stage_uid = stage_uid

        session.flush()
        stages = (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == workflow_id)
            .order_by(WorkflowStage.order.asc())
            .all()
        )
        stage_map = {stage.uid: int(stage.order or 0) for stage in stages}
        compute_batches(workflow, steps, stage_map)
        session.commit()
        return True


def move_stage_order(workflow_id: int, stage_uid: str, delta: int) -> bool:
    """Move a stage up or down and validate the resulting execution plan."""
    if not workflow_id or delta not in (-1, 1):
        return False

    with get_session() as session:
        stage = session.query(WorkflowStage).filter(WorkflowStage.uid == stage_uid).first()
        if not stage:
            return False

        stages = (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == workflow_id)
            .order_by(WorkflowStage.order.asc(), WorkflowStage.created_at.asc())
            .all()
        )
        index = next((i for i, item in enumerate(stages) if item.uid == stage_uid), None)
        if index is None:
            return False

        target_index = index + delta
        if target_index < 0 or target_index >= len(stages):
            return False

        other = stages[target_index]
        stage.order, other.order = int(other.order or 0), int(stage.order or 0)
        session.flush()

        _validate_workflow_plan(session, workflow_id)
        session.commit()
        return True


def plan_stage_migration(
    steps_sorted: list[Step],
    from_stage_uid: str,
    to_stage_uid: str,
) -> tuple[dict[int, str], list[int]]:
    """Build stage overrides and visual order for moving all steps between stages."""
    moving = [step for step in steps_sorted if getattr(step, "stage_uid", None) == from_stage_uid]
    if not moving:
        return {}, [step.id for step in steps_sorted]

    keep_ids = [step.id for step in steps_sorted if getattr(step, "stage_uid", None) != from_stage_uid]
    moving_ids = [step.id for step in moving]

    insert_at = 0
    for step in steps_sorted:
        if getattr(step, "stage_uid", None) != to_stage_uid:
            continue
        step_id = step.id
        if step_id in keep_ids:
            insert_at = keep_ids.index(step_id) + 1

    insert_at = max(0, min(insert_at, len(keep_ids)))
    new_order = keep_ids[:insert_at] + moving_ids + keep_ids[insert_at:]
    overrides = {step_id: to_stage_uid for step_id in moving_ids}
    return overrides, new_order


def migrate_stage_steps(workflow_id: int, from_stage_uid: str, to_stage_uid: str) -> bool:
    """Move all steps from one stage to another with execution-plan validation."""
    if not workflow_id:
        return False
    if from_stage_uid == to_stage_uid:
        return True

    steps_sorted = _stage_sorted_steps(workflow_id)
    overrides, new_order = plan_stage_migration(steps_sorted, from_stage_uid, to_stage_uid)
    if not overrides:
        return True
    return apply_orders_and_stage_updates(workflow_id, overrides, new_order)


def move_step_to_stage(workflow_id: int, step_id: int, target_stage_uid: str) -> bool:
    """Move one step to the end of a target stage with execution-plan validation."""
    if not workflow_id:
        return False

    steps_sorted = _stage_sorted_steps(workflow_id)
    step_ids = [step.id for step in steps_sorted]
    if step_id not in step_ids:
        return False

    step_ids.remove(step_id)
    insert_at = 0
    for index, step in enumerate(steps_sorted):
        if getattr(step, "stage_uid", None) == target_stage_uid:
            insert_at = index + 1

    insert_at = max(0, min(insert_at, len(step_ids)))
    step_ids.insert(insert_at, step_id)
    return apply_orders_and_stage_updates(workflow_id, {int(step_id): target_stage_uid}, step_ids)
