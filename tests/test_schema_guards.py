# -*- coding: utf-8 -*-
"""模式层守卫测试"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
from models import Step


def test_step_model_declares_unique_workflow_uid_index():
    indexes = {index.name: index for index in Step.__table__.indexes}

    assert "uq_steps_workflow_uid" in indexes
    unique_index = indexes["uq_steps_workflow_uid"]

    assert unique_index.unique is True
    assert [column.name for column in unique_index.columns] == ["workflow_id", "uid"]


def test_schema_version_record_is_committed(tmp_path: Path):
    db_path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{db_path}")

    database._ensure_schema_version_table(engine)
    database._record_version(engine, 7)

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_versions")).fetchall()

    assert rows == [(7,)]


def _use_temp_database(monkeypatch, tmp_path: Path):
    database.cleanup_session()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workflows.db")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_SessionFactory", None)
    monkeypatch.setattr(database, "_scoped_session", None)
    monkeypatch.setattr(database, "_init_done", False)
    database.init_db()
    return database


def test_json_import_export_preserves_execution_policy(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "workflow.json"
    payload_path.write_text(
        """
{
  "version": 1,
  "workflows": [
    {
      "id": "wf_policy",
      "name": "策略测试",
      "steps": [
        {
          "id": "step_policy",
          "name": "带策略步骤",
          "step_type": "python",
          "script": "job.py",
          "timeout_seconds": 123,
          "retry_count": 2,
          "skip_on_success": true
        }
      ]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    assert db.import_from_json(payload_path) == 1
    workflow = db.get_workflow_by_uid("wf_policy")
    steps = db.get_steps_by_workflow(workflow.id)

    assert steps[0].timeout_seconds == 123
    assert steps[0].retry_count == 2
    assert steps[0].skip_on_success is True

    exported_path = tmp_path / "exported.json"
    db.export_to_json(exported_path, workflow_ids=[workflow.id])
    exported = exported_path.read_text(encoding="utf-8")

    assert '"timeout_seconds": 123' in exported
    assert '"retry_count": 2' in exported
    assert '"skip_on_success": true' in exported


def test_clone_workflow_remaps_dependencies_to_later_steps(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("克隆依赖测试")
    step_a = db.create_step(workflow.id, "A", order=1)
    step_b = db.create_step(workflow.id, "B", order=2)
    db.update_step(step_a.id, depends_on=f'["{step_b.uid}"]')

    cloned = db.clone_workflow(workflow.id, "克隆结果")
    cloned_steps = db.get_steps_by_workflow(cloned.id)
    cloned_by_name = {step.name: step for step in cloned_steps}

    assert cloned_by_name["A"].get_depends_on() == [cloned_by_name["B"].uid]
