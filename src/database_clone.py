# -*- coding: utf-8 -*-
"""工作流克隆逻辑。"""

from __future__ import annotations

from typing import Callable, Optional

from models import Step, Workflow, WorkflowStage


def clone_workflow_impl(
    workflow_id: int,
    new_name: str | None = None,
    *,
    get_session: Callable[[], object],
    generate_uid: Callable[[], str],
) -> Optional[Workflow]:
    """克隆工作流（含阶段、步骤和步骤依赖 UID 重映射）。"""
    with get_session() as session:
        source = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not source:
            return None

        cloned = Workflow(
            uid=generate_uid(),
            name=new_name or f"{source.name} 副本",
            description=source.description,
            chart_theme=source.chart_theme,
            parallel_enabled=source.parallel_enabled,
            max_workers=source.max_workers,
            watch_enabled=source.watch_enabled,
            watch_mode=source.watch_mode,
            watch_folders=source.watch_folders,
            cooldown_seconds=source.cooldown_seconds,
            settle_seconds=source.settle_seconds,
            single_script_enabled=source.single_script_enabled,
            single_script_type=source.single_script_type,
            single_script_path=source.single_script_path,
            single_script_args=source.single_script_args,
            single_script_cwd=source.single_script_cwd,
            log_retention_days=source.log_retention_days,
            notify_config=source.notify_config,
        )
        session.add(cloned)
        session.flush()

        uid_map = _clone_stages(session, source, cloned.id, generate_uid)
        _clone_steps(session, source, cloned.id, uid_map, generate_uid)

        session.commit()
        session.refresh(cloned)
        return cloned


def _clone_stages(
    session,
    source: Workflow,
    cloned_workflow_id: int,
    generate_uid: Callable[[], str],
) -> dict[str, str]:
    uid_map = {}
    for stage in sorted(source.stages, key=lambda s: s.order or 0):
        new_uid = generate_uid()
        uid_map[stage.uid] = new_uid
        session.add(
            WorkflowStage(
                uid=new_uid,
                workflow_id=cloned_workflow_id,
                name=stage.name,
                order=stage.order,
                color=stage.color,
            )
        )
    return uid_map


def _clone_steps(
    session,
    source: Workflow,
    cloned_workflow_id: int,
    stage_uid_map: dict[str, str],
    generate_uid: Callable[[], str],
) -> None:
    source_steps = sorted(source.steps, key=lambda s: s.order)
    old_to_new_uid = {step.uid: generate_uid() for step in source_steps}
    for step in source_steps:
        new_deps = [old_to_new_uid.get(dep, dep) for dep in step.get_depends_on()]
        cloned_step = Step(
            uid=old_to_new_uid[step.uid],
            workflow_id=cloned_workflow_id,
            order=step.order,
            name=step.name,
            stage_uid=stage_uid_map.get(step.stage_uid, step.stage_uid),
            step_type=step.step_type,
            script_path=step.script_path,
            saved_run_args=step.saved_run_args,
            cwd=step.cwd,
            is_gate=step.is_gate,
            is_parallel=step.is_parallel,
            chart_theme=step.chart_theme,
            skip_on_success=step.skip_on_success,
            retry_count=step.retry_count,
            timeout_seconds=step.timeout_seconds,
            output_paths=step.output_paths,
        )
        cloned_step.set_args(step.get_args())
        cloned_step.set_depends_on(new_deps)
        session.add(cloned_step)
