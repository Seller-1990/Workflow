# -*- coding: utf-8 -*-
"""CLI 契约测试"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cli as cli_module


def test_cmd_export_only_exports_requested_workflow(tmp_path, monkeypatch, capsys):
    exported = {}

    monkeypatch.setattr(cli_module, "init_db", lambda: None)
    monkeypatch.setattr(cli_module, "resolve_workflow_id", lambda identifier: 5)
    monkeypatch.setattr(
        cli_module,
        "get_workflow_by_id",
        lambda workflow_id: type("WorkflowStub", (), {"id": 5, "name": "月度数据处理"})() if workflow_id == 5 else None,
    )

    def fake_export(output: Path, workflow_ids=None, include_secrets=False):
        exported["path"] = Path(output)
        exported["workflow_ids"] = workflow_ids
        exported["include_secrets"] = include_secrets
        exported["path"].write_text(
            json.dumps({"workflows": [{"name": "月度数据处理"}]}, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli_module, "export_to_json", fake_export)

    args = type("Args", (), {"workflow_id": "5", "output": str(tmp_path / "out.json")})()
    cli_module.cmd_export(args)

    assert exported["workflow_ids"] == [5]
    assert exported["include_secrets"] is False
    assert exported["path"].exists()
    output = capsys.readouterr().out
    assert "工作流已导出到" in output
    assert "Webhook URL 已脱敏" in output


def test_import_and_run_help_starts_without_import_error():
    script = Path(__file__).resolve().parent.parent / "_import_and_run.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "--auto" in result.stdout


def test_cmd_backup_masks_webhook_secrets_by_default(tmp_path, monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(cli_module, "init_db", lambda: None)

    def fake_backup(backup_dir=None, include_secrets=False):
        calls["backup_dir"] = backup_dir
        calls["include_secrets"] = include_secrets
        return tmp_path / "backup.json"

    monkeypatch.setattr(cli_module, "auto_backup_workflows", fake_backup)

    args = type("Args", (), {"dir": str(tmp_path), "include_secrets": False, "without_secrets": False})()
    cli_module.cmd_backup(args)

    assert calls == {"backup_dir": tmp_path, "include_secrets": False}
    output = capsys.readouterr().out
    assert "Webhook URL 已脱敏" in output


def test_cmd_backup_warns_when_secrets_are_included(tmp_path, monkeypatch, capsys):
    calls = {}

    monkeypatch.setattr(cli_module, "init_db", lambda: None)

    def fake_backup(backup_dir=None, include_secrets=False):
        calls["include_secrets"] = include_secrets
        return tmp_path / "backup.json"

    monkeypatch.setattr(cli_module, "auto_backup_workflows", fake_backup)

    args = type("Args", (), {"dir": None, "include_secrets": True, "without_secrets": False})()
    cli_module.cmd_backup(args)

    assert calls["include_secrets"] is True
    output = capsys.readouterr().out
    assert "包含完整 Webhook URL" in output
