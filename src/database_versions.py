# -*- coding: utf-8 -*-
"""工作流配置版本快照。"""

from __future__ import annotations

import json
from typing import Callable, Optional

from models import Workflow, WorkflowVersion


def save_workflow_version_impl(
    workflow_id: int,
    *,
    reason: str | None = None,
    session_factory: Callable,
) -> Optional[int]:
    """保存工作流当前配置的快照版本。"""
    with session_factory() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not workflow:
            return None

        latest = (
            session.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .first()
        )
        next_version = (latest.version + 1) if latest else 1

        version = WorkflowVersion(
            workflow_id=workflow_id,
            version=next_version,
            snapshot=build_workflow_snapshot(workflow),
            change_reason=reason,
        )
        session.add(version)
        session.commit()
        return next_version


def get_workflow_versions_impl(
    workflow_id: int,
    *,
    limit: int = 20,
    session_factory: Callable,
) -> list[WorkflowVersion]:
    """获取工作流的版本历史。"""
    with session_factory() as session:
        return (
            session.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(limit)
            .all()
        )


def get_workflow_version_impl(version_id: int, *, session_factory: Callable) -> Optional[WorkflowVersion]:
    """获取指定版本。"""
    with session_factory() as session:
        return session.query(WorkflowVersion).filter(WorkflowVersion.id == version_id).first()


def build_workflow_snapshot(workflow: Workflow) -> str:
    stages_data = [
        {
            "uid": stage.uid,
            "name": stage.name,
            "order": stage.order,
            "color": stage.color,
        }
        for stage in sorted(workflow.stages, key=lambda stage: stage.order or 0)
    ]
    steps_data = [
        {
            "uid": step.uid,
            "name": step.name,
            "stage_uid": step.stage_uid,
            "step_type": step.step_type,
            "script_path": step.script_path,
            "args": step.get_args(),
            "depends_on": step.get_depends_on(),
            "is_gate": step.is_gate,
            "is_parallel": step.is_parallel,
            "order": step.order,
            "chart_theme": step.chart_theme,
            "retry_count": step.retry_count,
            "timeout_seconds": step.timeout_seconds,
        }
        for step in sorted(workflow.steps, key=lambda step: step.order)
    ]
    return json.dumps(
        {
            "name": workflow.name,
            "stages": stages_data,
            "steps": steps_data,
            "parallel_enabled": workflow.parallel_enabled,
            "watch_enabled": workflow.watch_enabled,
        },
        ensure_ascii=False,
    )
