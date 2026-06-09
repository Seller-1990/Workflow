# -*- coding: utf-8 -*-
"""CLI 子进程 smoke 测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CLI_SCRIPT = ROOT_DIR / "src" / "cli.py"
WORKFLOW_APP_DATA_DIR_ENV = "WORKFLOW_APP_DATA_DIR"


def _build_subprocess_env(app_data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env[WORKFLOW_APP_DATA_DIR_ENV] = str(app_data_dir)
    return env


def _run_python(*args: str | Path, env: dict[str, str], cwd: Path = ROOT_DIR) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=env,
        cwd=cwd,
    )


def _run_cli(app_data_dir: Path, *args: str | Path) -> subprocess.CompletedProcess[str]:
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return _run_python(CLI_SCRIPT, *args, env=_build_subprocess_env(app_data_dir))


def _seed_workflow(app_data_dir: Path, workflow_name: str = "子进程导出工作流") -> None:
    result = _run_python(
        "-c",
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

from database import create_step, create_webhook, create_workflow, init_db, update_workflow

init_db()
workflow = create_workflow(sys.argv[1], description="subprocess smoke export")
create_step(
    workflow.id,
    name="导出步骤",
    step_type="python",
    script_path="scripts/export_demo.py",
    order=0,
)
webhook = create_webhook(
    name="子进程Webhook",
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=subprocess-secret-token",
    keyword="smoke",
    description="subprocess smoke test",
)
update_workflow(
    workflow.id,
    notify_config=json.dumps({"enabled": True, "webhook_id": webhook.id}, ensure_ascii=False),
)
""",
        workflow_name,
        env=_build_subprocess_env(app_data_dir),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_help_runs_in_subprocess_with_isolated_app_data(tmp_path):
    result = _run_cli(tmp_path / "help-app-data", "--help")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "Workflow CLI - 工作流命令行工具" in output
    assert "export" in output
    assert "WORKFLOW_APP_DATA_DIR" not in output


def test_cli_export_help_runs_in_subprocess_with_isolated_app_data(tmp_path):
    result = _run_cli(tmp_path / "export-help-app-data", "export", "--help")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "usage: cli.py export" in output
    assert "workflow_id" in output
    assert "--include-secrets" in output


def test_cli_export_writes_masked_json_in_subprocess(tmp_path):
    app_data_dir = tmp_path / "export-app-data"
    export_path = tmp_path / "workflow-export.json"

    _seed_workflow(app_data_dir)
    result = _run_cli(app_data_dir, "export", "子进程导出工作流", export_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert export_path.exists()

    output = result.stdout + result.stderr
    assert "工作流已导出到" in output
    assert "Webhook URL 已脱敏" in output

    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["secrets_included"] is False
    assert [workflow["name"] for workflow in payload["workflows"]] == ["子进程导出工作流"]
    assert payload["workflows"][0]["steps"][0]["name"] == "导出步骤"
    assert payload["webhooks"][0]["name"] == "子进程Webhook"
    assert payload["webhooks"][0]["webhook_url_masked"] is True
    assert "subprocess-secret-token" not in payload["webhooks"][0]["webhook_url"]
