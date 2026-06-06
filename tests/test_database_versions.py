# -*- coding: utf-8 -*-
"""工作流版本快照测试。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database


def _use_temp_database(monkeypatch, tmp_path: Path):
    database.cleanup_session()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "versions.db")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_SessionFactory", None)
    monkeypatch.setattr(database, "_scoped_session", None)
    monkeypatch.setattr(database, "_init_done", False)
    database.init_db()
    return database


def test_save_workflow_version_increments_and_snapshots_configuration(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("版本测试")
    stage = db.create_stage(workflow.id, "阶段A", order=1)
    step = db.create_step(
        workflow.id,
        "步骤A",
        step_type="python",
        script_path="job.py",
        order=1,
        stage_uid=stage.uid,
    )
    db.update_step(step.id, retry_count=2, timeout_seconds=123)

    assert db.save_workflow_version(workflow.id, reason="first") == 1
    assert db.save_workflow_version(workflow.id, reason="second") == 2

    versions = db.get_workflow_versions(workflow.id)
    assert [version.version for version in versions] == [2, 1]
    assert versions[0].change_reason == "second"

    loaded = db.get_workflow_version(versions[0].id)
    snapshot = json.loads(loaded.snapshot)
    assert snapshot["name"] == "版本测试"
    stages_by_name = {stage["name"]: stage for stage in snapshot["stages"]}
    assert "阶段A" in stages_by_name
    assert snapshot["steps"][0]["name"] == "步骤A"
    assert snapshot["steps"][0]["retry_count"] == 2
    assert snapshot["steps"][0]["timeout_seconds"] == 123
