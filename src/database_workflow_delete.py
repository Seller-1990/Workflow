# -*- coding: utf-8 -*-
"""Workflow deletion helpers."""

from __future__ import annotations

from typing import Callable

from sqlalchemy import or_

from models import (
    RecentWorkflow,
    RunHistory,
    Step,
    StepLog,
    Workflow,
    WorkflowStage,
    WorkflowVersion,
)


def delete_workflow_impl(workflow_id: int, *, get_session: Callable) -> bool:
    """Bulk-delete a workflow and related rows without ORM cascade loading."""

    with get_session() as session:
        workflow_row = (
            session.query(Workflow.id, Workflow.uid)
            .filter(Workflow.id == workflow_id)
            .first()
        )
        if not workflow_row:
            return False

        step_ids = [
            row.id for row in session.query(Step.id).filter(Step.workflow_id == workflow_id)
        ]
        history_ids = [
            row.id
            for row in session.query(RunHistory.id).filter(
                RunHistory.workflow_id == workflow_id
            )
        ]

        step_log_filters = []
        if history_ids:
            step_log_filters.append(StepLog.run_history_id.in_(history_ids))
        if step_ids:
            step_log_filters.append(StepLog.step_id.in_(step_ids))
        if step_log_filters:
            session.query(StepLog).filter(or_(*step_log_filters)).delete(
                synchronize_session=False
            )

        for model in (RunHistory, WorkflowVersion, Step, WorkflowStage):
            session.query(model).filter(model.workflow_id == workflow_id).delete(
                synchronize_session=False
            )
        session.query(RecentWorkflow).filter(
            RecentWorkflow.workflow_uid == workflow_row.uid
        ).delete(synchronize_session=False)
        session.query(Workflow).filter(Workflow.id == workflow_id).delete(
            synchronize_session=False
        )
        session.commit()
        return True
