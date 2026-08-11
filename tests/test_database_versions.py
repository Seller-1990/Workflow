# -*- coding: utf-8 -*-
"""工作流版本快照测试。"""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
import database_import_export
import database_versions
from models import WorkflowVersion


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
    workflow = db.create_workflow("版本测试", description="版本快照描述")
    webhook = db.create_webhook(
        "版本机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=local-token",
    )
    db.update_workflow(
        workflow.id,
        single_script_enabled=True,
        single_script_type="python",
        single_script_path="main.py",
        single_script_args=json.dumps(["--month", "2026-06"], ensure_ascii=False),
        single_script_cwd="jobs",
    )
    db.update_workflow(workflow.id, notify_config=json.dumps({"enabled": True, "webhook_id": webhook.id}))

    stage = db.create_stage(workflow.id, "阶段A", order=1)
    step = db.create_step(
        workflow.id,
        "步骤A",
        step_type="python",
        script_path="job.py",
        order=1,
        stage_uid=stage.uid,
    )
    db.update_step(
        step.id,
        retry_count=2,
        timeout_seconds=123,
        cwd="steps",
        skip_on_success=True,
        args=json.dumps(["--fixed", "1"], ensure_ascii=False),
        saved_run_args=json.dumps(["--year", "2026"], ensure_ascii=False),
        output_paths=json.dumps(["D:/reports"], ensure_ascii=False),
    )

    assert db.save_workflow_version(workflow.id, reason="first") == 1
    assert db.save_workflow_version(workflow.id, reason="second") == 2

    versions = db.get_workflow_versions(workflow.id)
    assert [version.version for version in versions] == [2, 1]
    assert versions[0].change_reason == "second"

    loaded = db.get_workflow_version(versions[0].id)
    snapshot = json.loads(loaded.snapshot)
    assert snapshot["snapshot_schema_version"] == database_versions.SNAPSHOT_SCHEMA_VERSION
    assert snapshot["id"] == workflow.uid
    assert snapshot["name"] == "版本测试"
    assert snapshot["description"] == "版本快照描述"
    stages_by_name = {stage["name"]: stage for stage in snapshot["stages"]}
    assert "阶段A" in stages_by_name
    assert snapshot["notify"] == {
        "enabled": True,
        "webhook_id": webhook.id,
        "webhook_name": "版本机器人",
    }
    assert snapshot["single_script"] == {
        "enabled": True,
        "type": "python",
        "path": "main.py",
        "args": ["--month", "2026-06"],
        "cwd": "jobs",
    }
    assert snapshot["steps"][0]["name"] == "步骤A"
    assert snapshot["steps"][0]["id"] == step.uid
    assert snapshot["steps"][0]["retry_count"] == 2
    assert snapshot["steps"][0]["timeout_seconds"] == 123
    assert snapshot["steps"][0]["script"] == "job.py"
    assert snapshot["steps"][0]["cwd"] == "steps"
    assert snapshot["steps"][0]["skip_on_success"] is True
    assert snapshot["steps"][0]["args"] == ["--fixed", "1"]
    assert snapshot["steps"][0]["saved_run_args"] == ["--year", "2026"]
    assert snapshot["steps"][0]["output_paths"] == ["D:/reports"]
    assert snapshot["parallel"] == {
        "enabled": False,
        "max_workers": 2,
    }

    export_path = tmp_path / "workflow-export.json"
    db.export_to_json(export_path, workflow_ids=[workflow.id], include_secrets=True)
    exported = json.loads(export_path.read_text(encoding="utf-8"))

    assert exported["workflows"][0] == {
        key: value
        for key, value in snapshot.items()
        if key != "snapshot_schema_version"
    }


def test_snapshot_schema_contract_matches_export_payload_keys(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("契约测试", description="快照契约说明")
    webhook = db.create_webhook(
        "契约机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=contract-token",
    )
    db.update_workflow(
        workflow.id,
        parallel_enabled=True,
        max_workers=4,
        single_script_enabled=True,
        single_script_type="python",
        single_script_path="contract.py",
        single_script_args=json.dumps(["--dry-run"], ensure_ascii=False),
        single_script_cwd="jobs",
        notify_config=json.dumps({"enabled": True, "webhook_id": webhook.id}, ensure_ascii=False),
    )
    stage = db.create_stage(workflow.id, "阶段A", order=1)
    db.create_step(
        workflow.id,
        "步骤A",
        step_type="python",
        script_path="contract.py",
        order=1,
        stage_uid=stage.uid,
    )

    assert db.save_workflow_version(workflow.id, reason="contract") == 1

    snapshot = json.loads(db.get_workflow_versions(workflow.id)[0].snapshot)
    expected_top_level_keys = {
        "snapshot_schema_version",
        "id",
        "name",
        "description",
        "chart_theme",
        "parallel",
        "notify",
        "single_script",
        "stages",
        "steps",
    }
    assert set(snapshot) == expected_top_level_keys
    assert snapshot["snapshot_schema_version"] == database_import_export.WORKFLOW_PAYLOAD_SCHEMA_VERSION
    assert snapshot["description"] == "快照契约说明"
    assert set(snapshot["parallel"]) == {"enabled", "max_workers"}
    assert set(snapshot["single_script"]) == {"enabled", "type", "path", "args", "cwd"}
    assert {"uid", "name", "order", "color"} <= set(snapshot["stages"][0])
    assert {
        "id",
        "name",
        "stage_uid",
        "step_type",
        "script",
        "args",
        "saved_run_args",
        "cwd",
        "is_gate",
        "is_parallel",
        "depends_on",
        "chart_theme",
        "timeout_seconds",
        "retry_count",
        "skip_on_success",
        "output_paths",
    } <= set(snapshot["steps"][0])
    assert {"enabled", "webhook_id", "webhook_name"} <= set(snapshot["notify"])


def test_workflow_version_model_declares_unique_workflow_version_index():
    indexes = {index.name: index for index in WorkflowVersion.__table__.indexes}

    assert "uq_workflow_versions_workflow_version" in indexes
    unique_index = indexes["uq_workflow_versions_workflow_version"]
    assert unique_index.unique is True
    assert [column.name for column in unique_index.columns] == ["workflow_id", "version"]


def test_workflow_version_unique_migration_renumbers_duplicates(tmp_path):
    db_path = tmp_path / "versions.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE workflows (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE workflow_versions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "workflow_id INTEGER NOT NULL,"
                "version INTEGER NOT NULL,"
                "snapshot TEXT NOT NULL,"
                "change_reason VARCHAR(255),"
                "created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )
        conn.execute(text("INSERT INTO workflows(id) VALUES (1)"))
        conn.execute(text("INSERT INTO workflow_versions(workflow_id, version, snapshot) VALUES (1, 1, '{}')"))
        conn.execute(text("INSERT INTO workflow_versions(workflow_id, version, snapshot) VALUES (1, 1, '{}')"))
        conn.execute(text("INSERT INTO workflow_versions(workflow_id, version, snapshot) VALUES (1, 2, '{}')"))

    database._ensure_workflow_version_unique(engine)

    with engine.connect() as conn:
        versions = conn.execute(
            text("SELECT version FROM workflow_versions WHERE workflow_id=1 ORDER BY version")
        ).fetchall()
        duplicate_count = conn.execute(text(
            "SELECT COUNT(*) FROM ("
            "SELECT workflow_id, version FROM workflow_versions "
            "GROUP BY workflow_id, version HAVING COUNT(*) > 1"
            ")"
        )).scalar_one()

    assert versions == [(1,), (2,), (3,)]
    assert duplicate_count == 0


def test_save_workflow_version_retries_on_version_collision(monkeypatch, tmp_path):
    class _Latest:
        version = 1

    class _WorkflowQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return object()

    class _VersionQuery:
        def __init__(self, session):
            self._session = session

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return self._session.latest_versions.pop(0)

    class _Session:
        def __init__(self):
            self.latest_versions = [None, _Latest()]
            self.added_versions = []
            self.commit_calls = 0
            self.rollback_calls = 0

        def query(self, model):
            if model is database_versions.Workflow:
                return _WorkflowQuery()
            return _VersionQuery(self)

        def add(self, version):
            self.added_versions.append(version.version)

        def commit(self):
            self.commit_calls += 1
            if self.commit_calls == 1:
                raise IntegrityError("insert workflow version", {}, Exception("duplicate"))

        def rollback(self):
            self.rollback_calls += 1

    session = _Session()
    monkeypatch.setattr(database_versions, "build_workflow_snapshot", lambda workflow: "{}")

    @contextmanager
    def session_factory():
        yield session

    assert database_versions.save_workflow_version_impl(
        1,
        reason="race",
        session_factory=session_factory,
    ) == 2
    assert session.added_versions == [1, 2]
    assert session.rollback_calls == 1
