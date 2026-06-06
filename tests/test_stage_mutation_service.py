# -*- coding: utf-8 -*-
"""Stage mutation service tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
import stage_mutation_service as service
from exceptions import DependencyError


def _use_temp_database(monkeypatch, tmp_path: Path):
    database.cleanup_session()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "stage_mutations.db")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_SessionFactory", None)
    monkeypatch.setattr(database, "_scoped_session", None)
    monkeypatch.setattr(database, "_init_done", False)
    database.init_db()
    return database


def _workflow_with_two_stages(db):
    workflow = db.create_workflow("阶段事务测试")
    default_stage = db.list_stages(workflow.id)[0]
    second_stage = db.create_stage(workflow.id, name="第二阶段")
    return workflow, default_stage, second_stage


def test_apply_orders_and_stage_updates_commits_in_one_transaction(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow, default_stage, second_stage = _workflow_with_two_stages(db)
    step_a = db.create_step(workflow.id, "A", order=0, stage_uid=default_stage.uid)
    step_b = db.create_step(workflow.id, "B", order=1, stage_uid=default_stage.uid)
    step_c = db.create_step(workflow.id, "C", order=2, stage_uid=second_stage.uid)

    ok = service.apply_orders_and_stage_updates(
        workflow.id,
        {step_a.id: second_stage.uid},
        [step_b.id, step_c.id, step_a.id],
    )

    assert ok is True
    steps = db.get_steps_by_workflow(workflow.id)
    by_name = {step.name: step for step in steps}
    assert [step.name for step in steps] == ["B", "C", "A"]
    assert by_name["A"].stage_uid == second_stage.uid
    assert by_name["A"].order == 2


def test_migrate_stage_steps_moves_all_source_stage_steps(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow, default_stage, second_stage = _workflow_with_two_stages(db)
    step_a = db.create_step(workflow.id, "A", order=0, stage_uid=default_stage.uid)
    step_b = db.create_step(workflow.id, "B", order=1, stage_uid=default_stage.uid)
    step_c = db.create_step(workflow.id, "C", order=2, stage_uid=second_stage.uid)

    ok = service.migrate_stage_steps(workflow.id, default_stage.uid, second_stage.uid)

    assert ok is True
    steps = db.get_steps_by_workflow(workflow.id)
    assert [step.id for step in steps] == [step_c.id, step_a.id, step_b.id]
    assert {step.stage_uid for step in steps} == {second_stage.uid}


def test_move_stage_order_rolls_back_when_future_dependency_would_be_created(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow, default_stage, second_stage = _workflow_with_two_stages(db)
    workflow_id = workflow.id
    default_stage_uid = default_stage.uid
    second_stage_uid = second_stage.uid
    step_a = db.create_step(workflow.id, "A", order=0, stage_uid=default_stage.uid)
    step_b = db.create_step(workflow.id, "B", order=1, stage_uid=second_stage.uid)
    db.update_step(step_b.id, depends_on=json.dumps([step_a.uid], ensure_ascii=False))

    with pytest.raises(DependencyError):
        service.move_stage_order(workflow_id, second_stage_uid, -1)

    stages = db.list_stages(workflow_id)
    by_uid = {stage.uid: stage for stage in stages}
    assert by_uid[default_stage_uid].order == 0
    assert by_uid[second_stage_uid].order == 1
