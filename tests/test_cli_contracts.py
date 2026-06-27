# -*- coding: utf-8 -*-
"""CLI 契约测试"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
CLI_SCRIPT = SRC_DIR / "cli.py"
WORKFLOW_APP_DATA_DIR_ENV = "WORKFLOW_APP_DATA_DIR"

sys.path.insert(0, str(SRC_DIR))

import cli as cli_module


def _build_subprocess_env(app_data_dir: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if app_data_dir is not None:
        env[WORKFLOW_APP_DATA_DIR_ENV] = str(app_data_dir)
    return env


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

    args = type("Args", (), {"workflow_id": "5", "output": str(tmp_path / "out.json"), "include_secrets": False})()
    cli_module.cmd_export(args)

    assert exported["workflow_ids"] == [5]
    assert exported["include_secrets"] is False
    assert exported["path"].exists()
    output = capsys.readouterr().out
    assert "工作流已导出到" in output
    assert "Webhook URL 已脱敏" in output


def test_cmd_export_warns_when_including_secrets(tmp_path, monkeypatch, capsys):
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
            json.dumps({"secrets_included": include_secrets}, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(cli_module, "export_to_json", fake_export)

    args = type("Args", (), {"workflow_id": "5", "output": str(tmp_path / "secret.json"), "include_secrets": True})()
    cli_module.cmd_export(args)

    assert exported["workflow_ids"] == [5]
    assert exported["include_secrets"] is True
    output = capsys.readouterr().out
    assert "工作流已导出到" in output
    assert "包含完整 Webhook URL" in output
    assert "请勿提交、同步或共享" in output


def test_cmd_export_missing_workflow_exits_nonzero(monkeypatch):
    monkeypatch.setattr(cli_module, "init_db", lambda: None)
    monkeypatch.setattr(cli_module, "resolve_workflow_id", lambda identifier: 404)
    monkeypatch.setattr(cli_module, "get_workflow_by_id", lambda workflow_id: None)

    args = type("Args", (), {"workflow_id": "missing", "output": None, "include_secrets": False})()

    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_export(args)

    assert exc.value.code == 1


def test_cmd_import_missing_file_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_module, "init_db", lambda: None)
    args = type("Args", (), {"json_path": str(tmp_path / "missing.json")})()

    with pytest.raises(SystemExit) as exc:
        cli_module.cmd_import(args)

    assert exc.value.code == 1


def _run_python_script(*args, env=None, cwd=None):
    result = subprocess.run(
        [sys.executable, *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=env,
        cwd=cwd or ROOT_DIR,
    )
    output = result.stdout + result.stderr
    assert "Traceback" not in output
    assert "ModuleNotFoundError" not in output
    return result


def _run_cli_command(app_data_dir: Path, *args):
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return _run_python_script(
        CLI_SCRIPT,
        *args,
        env=_build_subprocess_env(app_data_dir),
    )


def _run_inline_python(app_data_dir: Path, code: str, *args):
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return _run_python_script(
        "-c",
        code,
        *args,
        env=_build_subprocess_env(app_data_dir),
    )


def _load_last_json_line(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    assert lines, "子进程未输出可解析内容"
    return json.loads(lines[-1])


def _seed_cli_test_workflow(app_data_dir: Path, workflow_name: str = "合同测试工作流") -> None:
    result = _run_inline_python(
        app_data_dir,
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

from database import create_step, create_webhook, create_workflow, init_db, update_workflow

init_db()
workflow = create_workflow(sys.argv[1], description="CLI contract integration test")
create_step(
    workflow.id,
    name="准备导出",
    step_type="python",
    script_path="scripts/demo_export.py",
    order=0,
)
webhook = create_webhook(
    name="合同测试Webhook",
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=integration-secret-token",
    keyword="合同",
    description="CLI contract test",
)
update_workflow(
    workflow.id,
    notify_config=json.dumps({"enabled": True, "webhook_id": webhook.id}, ensure_ascii=False),
)
print(json.dumps({"workflow_name": workflow.name, "webhook_id": webhook.id}, ensure_ascii=False))
""",
        workflow_name,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _inspect_cli_test_workflow(app_data_dir: Path, workflow_name: str = "合同测试工作流") -> dict:
    result = _run_inline_python(
        app_data_dir,
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

from database import get_steps_by_workflow, get_workflow_by_name, init_db, list_webhooks

init_db()
workflow = get_workflow_by_name(sys.argv[1])
payload = {
    "workflow_exists": workflow is not None,
    "description": "",
    "step_names": [],
    "notify": {},
    "webhook_count": len(list_webhooks()),
}
if workflow is not None:
    payload["description"] = workflow.description or ""
    payload["step_names"] = [step.name for step in get_steps_by_workflow(workflow.id)]
    payload["notify"] = workflow.get_notify_config()
print(json.dumps(payload, ensure_ascii=False))
""",
        workflow_name,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return _load_last_json_line(result.stdout)


def test_cli_help_smoke_for_documented_entrypoints():
    cases = [
        (CLI_SCRIPT, "--help", "Workflow CLI"),
        (CLI_SCRIPT, "export", "--help", "--include-secrets"),
        (ROOT_DIR / "_import_and_run.py", "--help", "--auto"),
    ]

    for script, *args, expected_text in cases:
        result = _run_python_script(script, *args)
        assert result.returncode == 0
        assert expected_text in (result.stdout + result.stderr)


def test_cli_export_subprocess_writes_masked_json(tmp_path):
    app_data_dir = tmp_path / "export-app-data"
    export_path = tmp_path / "workflow-export.json"

    _seed_cli_test_workflow(app_data_dir)

    result = _run_cli_command(app_data_dir, "export", "合同测试工作流", export_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert export_path.exists()
    output = result.stdout + result.stderr
    assert "工作流已导出到" in output
    assert "Webhook URL 已脱敏" in output

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["secrets_included"] is False
    assert [workflow["name"] for workflow in payload["workflows"]] == ["合同测试工作流"]
    assert payload["workflows"][0]["description"] == "CLI contract integration test"
    assert payload["workflows"][0]["steps"][0]["name"] == "准备导出"
    assert payload["webhooks"][0]["name"] == "合同测试Webhook"
    assert payload["webhooks"][0]["webhook_url_masked"] is True
    assert "integration-secret-token" not in payload["webhooks"][0]["webhook_url"]


def test_cli_import_subprocess_imports_workflow_from_export(tmp_path):
    source_app_data_dir = tmp_path / "source-app-data"
    target_app_data_dir = tmp_path / "target-app-data"
    export_path = tmp_path / "workflow-export.json"

    _seed_cli_test_workflow(source_app_data_dir)
    export_result = _run_cli_command(source_app_data_dir, "export", "合同测试工作流", export_path)
    assert export_result.returncode == 0, export_result.stdout + export_result.stderr

    result = _run_cli_command(target_app_data_dir, "import", export_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "成功导入 1 个工作流" in (result.stdout + result.stderr)

    state = _inspect_cli_test_workflow(target_app_data_dir)
    assert state["workflow_exists"] is True
    assert state["description"] == "CLI contract integration test"
    assert state["step_names"] == ["准备导出"]
    assert state["notify"]["webhook_name"] == "合同测试Webhook"
    assert state["notify"]["webhook_id"] is None
    assert state["webhook_count"] == 0


def test_cli_backup_subprocess_creates_masked_backup(tmp_path):
    app_data_dir = tmp_path / "backup-app-data"
    backup_dir = tmp_path / "backups"

    _seed_cli_test_workflow(app_data_dir)

    result = _run_cli_command(app_data_dir, "backup", "--dir", backup_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "备份完成" in output
    assert "Webhook URL 已脱敏" in output

    backup_files = sorted(backup_dir.glob("workflows_backup_*.json"))
    assert len(backup_files) == 1

    payload = json.loads(backup_files[0].read_text(encoding="utf-8"))
    assert payload["secrets_included"] is False
    assert [workflow["name"] for workflow in payload["workflows"]] == ["合同测试工作流"]
    assert payload["webhooks"][0]["webhook_url_masked"] is True
    assert "integration-secret-token" not in json.dumps(payload, ensure_ascii=False)


def test_import_and_run_import_requires_existing_json_file(tmp_path):
    script = ROOT_DIR / "_import_and_run.py"
    missing_json = tmp_path / "missing.json"

    result = _run_python_script(script, "--workflows-json", missing_json, "import")

    assert result.returncode != 0
    assert "工作流导入文件不存在" in (result.stdout + result.stderr)


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
