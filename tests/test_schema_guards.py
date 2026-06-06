# -*- coding: utf-8 -*-
"""模式层守卫测试"""

import json
import sys
from pathlib import Path

import pytest
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


def test_copy_workflow_uses_clone_dependency_remap(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("复制依赖测试")
    step_a = db.create_step(workflow.id, "A", order=1)
    step_b = db.create_step(workflow.id, "B", order=2)
    db.update_step(step_a.id, depends_on=f'["{step_b.uid}"]')

    copied = db.copy_workflow(workflow.id, "复制结果")
    copied_steps = db.get_steps_by_workflow(copied.id)
    copied_by_name = {step.name: step for step in copied_steps}

    assert copied_by_name["A"].get_depends_on() == [copied_by_name["B"].uid]


def test_export_masks_webhook_url_by_default(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    secret_url = "https://oapi.dingtalk.com/robot/send?access_token=secret-token"
    db.create_webhook("财务机器人", secret_url, keyword="财务", description="生产通知")

    masked_path = tmp_path / "masked.json"
    db.export_to_json(masked_path)
    masked = json.loads(masked_path.read_text(encoding="utf-8"))

    assert masked["secrets_included"] is False
    assert masked["webhooks"][0]["webhook_url"] == db.MASKED_WEBHOOK_URL
    assert masked["webhooks"][0]["webhook_url_masked"] is True
    assert secret_url not in masked_path.read_text(encoding="utf-8")

    secret_path = tmp_path / "with-secrets.json"
    db.export_to_json(secret_path, include_secrets=True)
    with_secrets = json.loads(secret_path.read_text(encoding="utf-8"))

    assert with_secrets["secrets_included"] is True
    assert with_secrets["webhooks"][0]["webhook_url"] == secret_url
    assert with_secrets["webhooks"][0]["webhook_url_masked"] is False


def test_import_masked_webhook_does_not_overwrite_existing_url(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    existing = db.create_webhook(
        "财务机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=local-token",
        keyword="旧",
        description="旧备注",
    )
    payload_path = tmp_path / "masked-import.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": "财务机器人",
                        "webhook_url": db.MASKED_WEBHOOK_URL,
                        "webhook_url_masked": True,
                        "keyword": "新",
                        "description": "新备注",
                    }
                ],
                "workflows": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert db.import_from_json(payload_path) == 0

    updated = db.get_webhook_by_id(existing.id)
    assert updated.webhook_url.endswith("access_token=local-token")
    assert updated.keyword == "新"
    assert updated.description == "新备注"


def test_pending_migration_failure_raises(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{db_path}")
    database._ensure_schema_version_table(engine)

    def _broken_migration(_engine):
        raise ValueError("boom")

    monkeypatch.setitem(database.__dict__, "_broken_migration_for_test", _broken_migration)
    monkeypatch.setattr(database, "SCHEMA_MIGRATIONS", [(99, "_broken_migration_for_test")])

    with pytest.raises(RuntimeError, match="schema 迁移 v99 失败"):
        database._run_pending_migrations(engine)


def test_update_step_rejects_unknown_fields(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("字段契约测试")
    step = db.create_step(workflow.id, "A", order=1)

    with pytest.raises(ValueError, match="Step 不支持更新字段: timeout_second"):
        db.update_step(step.id, timeout_second=30)


def test_update_workflow_rejects_unknown_fields(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("工作流字段契约测试")

    with pytest.raises(ValueError, match="Workflow 不支持更新字段: max_worker"):
        db.update_workflow(workflow.id, max_worker=3)


def test_update_webhook_rejects_unknown_fields(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    webhook = db.create_webhook(
        "字段契约机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=token",
    )

    with pytest.raises(ValueError, match="WebhookConfig 不支持更新字段: url"):
        db.update_webhook(webhook.id, url="https://example.com")
