# -*- coding: utf-8 -*-
"""R4: _import_and_run.py 导入告警输出测试。

验证月度批量脚本的 import 子命令与 --auto 路径都会逐条打印
ImportResult.warnings（中文告警），而不是只输出导入数量。

DB 隔离遵循 test_import_warnings.py / test_cli_contracts.py 的既有模式：
子进程 + WORKFLOW_APP_DATA_DIR 环境变量指向 tmp_path，避免污染真实数据库。
注意 argparse 父 parser 选项（--workflows-json）须位于子命令（import）之前。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
IMPORT_AND_RUN_SCRIPT = ROOT_DIR / "_import_and_run.py"
WORKFLOW_APP_DATA_DIR_ENV = "WORKFLOW_APP_DATA_DIR"
MASKED_PLACEHOLDER = "__WORKFLOW_WEBHOOK_URL_MASKED__"


def _build_subprocess_env(app_data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env[WORKFLOW_APP_DATA_DIR_ENV] = str(app_data_dir)
    return env


def _run_import_and_run(
    app_data_dir: Path, payload_path: Path, *args
) -> subprocess.CompletedProcess[str]:
    app_data_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        # --workflows-json 是父 parser 选项，必须放在子命令之前
        [sys.executable, str(IMPORT_AND_RUN_SCRIPT), "--workflows-json", str(payload_path), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=_build_subprocess_env(app_data_dir),
        cwd=ROOT_DIR,
    )
    output = result.stdout + result.stderr
    assert "Traceback" not in output, output
    assert "ModuleNotFoundError" not in output, output
    return result


def _build_masked_payload(path: Path) -> None:
    """构造含脱敏 webhook 引用的导入 JSON（与 test_import_warnings.py 同构）。"""
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": "脱敏机器人",
                        "webhook_url": MASKED_PLACEHOLDER,
                        "webhook_url_masked": True,
                        "keyword": "",
                        "description": "",
                    }
                ],
                "workflows": [
                    {
                        "id": "wf_masked_notify",
                        "name": "通知告警工作流",
                        "notify": {"enabled": True, "webhook_name": "脱敏机器人"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_import_subcommand_prints_count_and_warnings(tmp_path):
    """import 子命令：输出导入数量并逐条打印中文告警。"""
    app_data_dir = tmp_path / "import-app-data"
    payload_path = tmp_path / "masked-import.json"
    _build_masked_payload(payload_path)

    result = _run_import_and_run(app_data_dir, payload_path, "import")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout
    assert "导入完成: 1 个工作流" in output
    assert "警告: " in output
    assert "脱敏机器人" in output
    assert "已跳过创建" in output
    assert "通知将不会发送" in output


def test_auto_path_prints_warnings_before_run(tmp_path):
    """--auto 路径同样走 cmd_import，告警须在运行前输出。"""
    app_data_dir = tmp_path / "auto-app-data"
    payload_path = tmp_path / "masked-auto.json"
    _build_masked_payload(payload_path)

    result = _run_import_and_run(app_data_dir, payload_path, "--auto")

    output = result.stdout + result.stderr
    assert "导入完成: 1 个工作流" in output
    assert "警告: " in output
    assert "脱敏机器人" in output
    assert "已跳过创建" in output
    assert "通知将不会发送" in output
    # 库中没有"月度数据处理"，cmd_run 找不到即退出 1；告警已在退出前输出，
    # 证明 --auto 路径确实调用了 cmd_import 且没有吞掉告警。
    assert result.returncode == 1
