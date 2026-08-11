# -*- coding: utf-8 -*-
"""模式层守卫测试"""

import logging
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
from models import RunHistory, Step, StepLog, WebhookConfig

from _schema_guard_utils import _use_temp_database


def test_step_model_declares_unique_workflow_uid_index():
    indexes = {index.name: index for index in Step.__table__.indexes}

    assert "uq_steps_workflow_uid" in indexes
    unique_index = indexes["uq_steps_workflow_uid"]

    assert unique_index.unique is True
    assert [column.name for column in unique_index.columns] == ["workflow_id", "uid"]


def test_step_saved_run_args_model_enforces_string_list(caplog):
    step = Step(uid="saved-args-model", workflow_id=1, name="测试")

    step.set_saved_run_args(["--year", "2026"])
    assert step.get_saved_run_args() == ["--year", "2026"]

    with pytest.raises(ValueError, match="字符串数组"):
        step.set_saved_run_args(["--year", 2026])

    step.saved_run_args = '["--year", 2026]'
    with caplog.at_level(logging.WARNING):
        assert step.get_saved_run_args() == []
    assert "不是字符串数组" in caplog.text


def test_webhook_model_declares_unique_name_index():
    indexes = {index.name: index for index in WebhookConfig.__table__.indexes}

    assert "uq_webhook_configs_name" in indexes
    unique_index = indexes["uq_webhook_configs_name"]

    assert unique_index.unique is True
    assert [column.name for column in unique_index.columns] == ["name"]


def test_run_history_and_step_log_models_declare_perf_indexes():
    run_indexes = {index.name: index for index in RunHistory.__table__.indexes}
    step_indexes = {index.name: index for index in StepLog.__table__.indexes}

    assert [column.name for column in run_indexes["ix_run_histories_wf_start_id"].columns] == [
        "workflow_id",
        "start_time",
        "id",
    ]
    assert [column.name for column in step_indexes["ix_step_logs_run_order"].columns] == [
        "run_history_id",
        "order",
    ]


def test_pending_migrations_create_recoverable_snapshot(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sentinel(value TEXT)"))
        conn.execute(text("INSERT INTO sentinel(value) VALUES ('before')"))
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    monkeypatch.setattr(database, "SCHEMA_MIGRATIONS", [(1, "_migration_for_snapshot_test")])

    def migration(target_engine):
        with target_engine.begin() as conn:
            conn.execute(text("UPDATE sentinel SET value='after'"))

    monkeypatch.setitem(database.__dict__, "_migration_for_snapshot_test", migration)

    database._ensure_schema_version_table(engine)
    database._run_pending_migrations(engine)

    snapshots = list((tmp_path / "migration_backups").glob("schema_before_v1_*.db"))
    assert len(snapshots) == 1
    snapshot_engine = create_engine(f"sqlite:///{snapshots[0]}")
    with snapshot_engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM sentinel")).scalar_one() == "before"

def test_schema_version_record_is_committed(tmp_path: Path):
    db_path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{db_path}")

    database._ensure_schema_version_table(engine)
    database._record_version(engine, 7)

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_versions")).fetchall()

    assert rows == [(7,)]


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


def test_step_copy_and_workflow_clone_preserve_runtime_args_and_output_paths(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("步骤字段复制测试")
    source = db.create_step(workflow.id, "A", order=1)
    fixed_args = ["--fixed", "1"]
    saved_args = ["--saved", "2"]
    output_paths = ["D:/outputs", "D:/reports/result.xlsx"]
    db.update_step(
        source.id,
        args=json.dumps(fixed_args, ensure_ascii=False),
        saved_run_args=json.dumps(saved_args, ensure_ascii=False),
        output_paths=json.dumps(output_paths, ensure_ascii=False),
    )

    copied = db.copy_step(source.id)
    cloned = db.clone_workflow(workflow.id, "克隆结果")
    cloned_source = next(step for step in db.get_steps_by_workflow(cloned.id) if step.name == "A")

    assert copied.get_args() == fixed_args
    assert copied.get_saved_run_args() == saved_args
    assert copied.get_output_paths() == output_paths
    assert cloned_source.get_args() == fixed_args
    assert cloned_source.get_saved_run_args() == saved_args
    assert cloned_source.get_output_paths() == output_paths


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


def test_single_workflow_export_only_includes_referenced_webhooks(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    target = db.create_workflow("目标工作流")
    other = db.create_workflow("其他工作流")
    target_webhook = db.create_webhook(
        "目标机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=dev-token",
    )
    other_webhook = db.create_webhook(
        "其他机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=other-token",
    )
    db.update_workflow(
        target.id,
        notify_config=json.dumps({"enabled": True, "webhook_id": target_webhook.id}, ensure_ascii=False),
    )
    db.update_workflow(
        other.id,
        notify_config=json.dumps({"enabled": True, "webhook_id": other_webhook.id}, ensure_ascii=False),
    )

    export_path = tmp_path / "single-workflow.json"
    db.export_to_json(export_path, workflow_ids=[target.id], include_secrets=True)
    exported = json.loads(export_path.read_text(encoding="utf-8"))

    assert [item["name"] for item in exported["webhooks"]] == ["目标机器人"]
    assert "access_token=dev-token" in export_path.read_text(encoding="utf-8")
    assert "access_token=other-token" not in export_path.read_text(encoding="utf-8")


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


def test_import_rejects_ambiguous_local_webhook_name(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    with db.get_session() as session:
        session.execute(text("DROP INDEX IF EXISTS uq_webhook_configs_name"))
        session.execute(text(
            "INSERT INTO webhook_configs(name, webhook_url, created_at, updated_at) VALUES "
            "('重复机器人', 'https://oapi.dingtalk.com/robot/send?access_token=local-a', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),"
            "('重复机器人', 'https://oapi.dingtalk.com/robot/send?access_token=local-b', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
        session.commit()

    payload_path = tmp_path / "ambiguous-webhook.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": "重复机器人",
                        "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=imported",
                    }
                ],
                "workflows": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Webhook 名称重复，无法确定绑定: 重复机器人"):
        db.import_from_json(payload_path)


def test_import_same_name_webhook_keeps_local_url_and_binds_workflow(monkeypatch, tmp_path: Path, caplog):
    db = _use_temp_database(monkeypatch, tmp_path)
    existing = db.create_webhook(
        "财务机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=local-token",
        keyword="旧",
        description="旧备注",
    )
    payload_path = tmp_path / "same-name-webhook.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": "财务机器人",
                        "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=imported-token",
                        "keyword": "新",
                        "description": "新备注",
                    }
                ],
                "workflows": [
                    {
                        "id": "wf_notify",
                        "name": "通知导入",
                        "notify": {"enabled": True, "webhook_name": "财务机器人"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="database_import_export"):
        assert db.import_from_json(payload_path) == 1

    updated = db.get_webhook_by_id(existing.id)
    assert updated.webhook_url.endswith("access_token=local-token")
    assert updated.keyword == "新"
    assert updated.description == "新备注"
    workflow = db.get_workflow_by_uid("wf_notify")
    assert workflow.get_notify_config()["webhook_id"] == existing.id
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "同名不同 URL" in messages
    assert "access_token=<redacted>" in messages
    assert "access_token=local-token" not in messages
    assert "access_token=imported-token" not in messages


def test_json_import_duplicate_workflow_uid_is_idempotent(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "workflow.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [{"id": "wf_once", "name": "只导入一次"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert db.import_from_json(payload_path) == 1
    assert db.import_from_json(payload_path) == 0
    assert len([wf for wf in db.list_workflows() if wf.uid == "wf_once"]) == 1


def test_import_ignores_bare_webhook_id_without_name_mapping(monkeypatch, tmp_path: Path, caplog):
    db = _use_temp_database(monkeypatch, tmp_path)
    local_webhook = db.create_webhook(
        "本机机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=local-token",
    )
    payload_path = tmp_path / "bare-webhook-id.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bare_id",
                        "name": "裸 ID 通知",
                        "notify": {"enabled": True, "webhook_id": local_webhook.id},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="database_import_export"):
        assert db.import_from_json(payload_path) == 1

    workflow = db.get_workflow_by_uid("wf_bare_id")
    assert workflow.get_notify_config()["webhook_id"] is None
    assert "忽略跨环境裸 webhook_id" in "\n".join(record.getMessage() for record in caplog.records)


def test_create_run_history_returns_known_fields_when_refresh_after_commit_fails(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("运行刷新失败")
    original_refresh = db.Session.refresh

    def broken_refresh(session, instance, *args, **kwargs):
        if isinstance(instance, RunHistory):
            raise ValueError("refresh failed")
        return original_refresh(session, instance, *args, **kwargs)

    monkeypatch.setattr(db.Session, "refresh", broken_refresh)

    run_history = db.create_run_history(workflow.id, reason="manual")

    assert run_history.id is not None
    assert run_history.run_id
    assert run_history.trace_id == run_history.run_id
    stored = db.get_latest_run_history(workflow.id)
    assert stored.id == run_history.id
    assert stored.status == "pending"


def test_create_step_log_does_not_retry_after_refresh_failure(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("步骤日志刷新失败")
    step = db.create_step(workflow.id, "A", order=1)
    run_history = db.create_run_history(workflow.id)
    original_refresh = db.Session.refresh

    def broken_refresh(session, instance, *args, **kwargs):
        if isinstance(instance, StepLog):
            raise ValueError("refresh failed")
        return original_refresh(session, instance, *args, **kwargs)

    monkeypatch.setattr(db.Session, "refresh", broken_refresh)

    step_log = db.create_step_log(run_history.id, step.id, order=7)

    assert step_log.id is not None
    assert step_log.run_history_id == run_history.id
    logs = db.get_step_logs_by_run(run_history.id)
    assert [(log.id, log.step_id, log.order, log.status) for log in logs] == [
        (step_log.id, step.id, 7, "pending")
    ]


def test_import_marks_risky_script_paths_for_review(monkeypatch, tmp_path: Path, caplog):
    """R1: 导入含风险路径（绝对路径/.. 逃逸）的工作流强制 review_required=1、digest 空。

    旧文本标记（[导入提示]）不再追加到 description；退役字段 single_script 不参与。
    """
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "risky-paths.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_risky_paths",
                        "name": "路径复核",
                        "description": "原说明",
                        "single_script": {
                            "enabled": True,
                            "type": "python",
                            "path": "C:/untrusted/job.py",
                            "cwd": "jobs",
                        },
                        "steps": [
                            {
                                "id": "step_risky",
                                "name": "Step",
                                "step_type": "python",
                                "script": "../outside.py",
                                "cwd": "safe",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="database_import_export"):
        assert db.import_from_json(payload_path) == 1

    workflow = db.get_workflow_by_uid("wf_risky_paths")

    # description 不再追加旧文本标记（旧文本不参与运行判定）
    assert workflow.description == "原说明"
    assert "[导入提示]" not in workflow.description
    # 新状态列：强制要求确认、digest 空、revision 因步骤写入递增
    assert workflow.risky_paths_review_required == 1
    assert workflow.risky_paths_confirmed_digest is None
    assert workflow.risky_paths_revision >= 1
    assert "需复核的脚本路径" in caplog.text


def test_retired_single_script_field_import_ok_and_not_exported(monkeypatch, tmp_path: Path):
    """退役字段 single_script：旧 JSON 含该对象可正常导入，导出不再包含该对象。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "single-script-retired.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_single",
                        "name": "单脚本",
                        "single_script": {
                            "enabled": True,
                            "type": "python",
                            "path": "job.py",
                            "args": ["--month", "2026-06"],
                            "cwd": "jobs",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert db.import_from_json(payload_path) == 1
    workflow = db.get_workflow_by_uid("wf_single")
    exported_path = tmp_path / "exported.json"
    db.export_to_json(exported_path, workflow_ids=[workflow.id])
    exported = json.loads(exported_path.read_text(encoding="utf-8"))

    assert "single_script" not in exported["workflows"][0]


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


def test_perf_index_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "perf-indexes.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE workflows (id INTEGER PRIMARY KEY)"))
        conn.execute(text(
            "CREATE TABLE run_histories ("
            "id INTEGER PRIMARY KEY,"
            "workflow_id INTEGER NOT NULL,"
            "start_time DATETIME"
            ")"
        ))
        conn.execute(text(
            "CREATE TABLE step_logs ("
            "id INTEGER PRIMARY KEY,"
            "run_history_id INTEGER NOT NULL,"
            "\"order\" INTEGER"
            ")"
        ))

    database._migrate_v8_run_history_step_log_perf_indexes(engine)
    database._migrate_v8_run_history_step_log_perf_indexes(engine)

    with engine.connect() as conn:
        run_indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(run_histories)"))}
        step_indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(step_logs)"))}

    assert "ix_run_histories_wf_start_id" in run_indexes
    assert "ix_step_logs_run_order" in step_indexes


def test_saved_run_args_migration_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "saved-run-args.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE steps (id INTEGER PRIMARY KEY)"))

    database._migrate_v9_step_saved_run_args(engine)
    database._migrate_v9_step_saved_run_args(engine)

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(steps)"))}

    assert "saved_run_args" in columns
    assert (9, "_migrate_v9_step_saved_run_args") in database.SCHEMA_MIGRATIONS


def test_step_uid_dedup_migration_repoints_step_logs(tmp_path: Path):
    db_path = tmp_path / "dedupe.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("CREATE TABLE workflows (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE steps ("
                "id INTEGER PRIMARY KEY,"
                "workflow_id INTEGER NOT NULL,"
                "uid TEXT NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE step_logs ("
                "id INTEGER PRIMARY KEY,"
                "step_id INTEGER NOT NULL REFERENCES steps(id)"
                ")"
            )
        )
        conn.execute(text("INSERT INTO workflows(id) VALUES (1)"))
        conn.execute(text("INSERT INTO steps(id, workflow_id, uid) VALUES (10, 1, 'dup')"))
        conn.execute(text("INSERT INTO steps(id, workflow_id, uid) VALUES (11, 1, 'dup')"))
        conn.execute(text("INSERT INTO step_logs(id, step_id) VALUES (99, 10)"))

    database._ensure_step_uid_unique(engine)

    with engine.connect() as conn:
        steps = conn.execute(text("SELECT id FROM steps ORDER BY id")).fetchall()
        step_log = conn.execute(text("SELECT step_id FROM step_logs WHERE id = 99")).scalar_one()

    assert steps == [(11,)]
    assert step_log == 11


def test_step_uid_unique_index_creation_failure_raises():
    class EmptyResult:
        def fetchall(self):
            return []

    class FakeConnection:
        def execute(self, statement, params=None):
            sql = str(statement)
            if "CREATE UNIQUE INDEX IF NOT EXISTS uq_steps_workflow_uid" in sql:
                raise RuntimeError("index failed")
            if "GROUP BY workflow_id, uid" in sql:
                return EmptyResult()
            raise AssertionError(f"unexpected SQL: {sql}")

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    with pytest.raises(RuntimeError, match="index failed"):
        database._ensure_step_uid_unique(FakeEngine())


def test_webhook_name_unique_migration_deduplicates_and_repoints_notify_config(tmp_path: Path):
    db_path = tmp_path / "webhook-dedupe.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE webhook_configs ("
            "id INTEGER PRIMARY KEY,"
            "name VARCHAR(100) NOT NULL,"
            "webhook_url TEXT NOT NULL,"
            "keyword VARCHAR(100),"
            "description TEXT,"
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
            "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))
        conn.execute(text(
            "CREATE TABLE workflows ("
            "id INTEGER PRIMARY KEY,"
            "notify_config TEXT"
            ")"
        ))
        conn.execute(text(
            "INSERT INTO webhook_configs(id, name, webhook_url) VALUES "
            "(1, '财务机器人', 'https://oapi.dingtalk.com/robot/send?access_token=keep'),"
            "(2, '财务机器人', 'https://oapi.dingtalk.com/robot/send?access_token=drop')"
        ))
        conn.execute(text(
            "INSERT INTO workflows(id, notify_config) VALUES "
            "(9, '{\"enabled\": true, \"webhook_id\": 2, \"webhook_name\": \"财务机器人\"}')"
        ))

    database._ensure_webhook_name_unique(engine)

    with engine.connect() as conn:
        webhooks = conn.execute(text("SELECT id, name FROM webhook_configs ORDER BY id")).fetchall()
        notify_config = conn.execute(text("SELECT notify_config FROM workflows WHERE id = 9")).scalar_one()
        index_names = {
            row[1]
            for row in conn.execute(text("PRAGMA index_list('webhook_configs')")).fetchall()
        }

    assert webhooks == [(1, "财务机器人")]
    assert json.loads(notify_config)["webhook_id"] == 1
    assert "uq_webhook_configs_name" in index_names
