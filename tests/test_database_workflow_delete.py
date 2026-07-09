# -*- coding: utf-8 -*-
"""Workflow deletion contract tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from models import RecentWorkflow, RunHistory, Step, StepLog, WorkflowStage, WorkflowVersion
from _schema_guard_utils import _use_temp_database


def test_delete_workflow_bulk_deletes_related_rows(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("删除批量清理测试")
    step = db.create_step(workflow.id, "待删步骤", order=1)
    run_history = db.create_run_history(workflow.id)
    workflow_id = workflow.id
    workflow_uid = workflow.uid
    step_id = step.id
    db.create_step_log(run_history.id, step.id, order=1)
    db.save_workflow_version(workflow.id, reason="delete cleanup")
    db.update_recent_workflow(workflow.uid)

    assert db.delete_workflow(workflow_id) is True

    with db.get_session() as session:
        assert session.query(Step).filter(Step.workflow_id == workflow_id).count() == 0
        assert session.query(WorkflowStage).filter(WorkflowStage.workflow_id == workflow_id).count() == 0
        assert session.query(RunHistory).filter(RunHistory.workflow_id == workflow_id).count() == 0
        assert session.query(StepLog).filter(StepLog.step_id == step_id).count() == 0
        assert session.query(WorkflowVersion).filter(WorkflowVersion.workflow_id == workflow_id).count() == 0
        assert session.query(RecentWorkflow).filter(RecentWorkflow.workflow_uid == workflow_uid).count() == 0

    assert db.delete_workflow(workflow_id) is False
