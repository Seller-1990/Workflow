# -*- coding: utf-8 -*-
"""导入告警（M2）与通知目标解析（L2）测试。

DB 隔离遵循 test_cli_contracts.py 的既有模式：
子进程 + WORKFLOW_APP_DATA_DIR 环境变量指向 tmp_path，避免污染真实数据库。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
WORKFLOW_APP_DATA_DIR_ENV = "WORKFLOW_APP_DATA_DIR"

sys.path.insert(0, str(SRC_DIR))

import notifier


def _build_subprocess_env(app_data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env[WORKFLOW_APP_DATA_DIR_ENV] = str(app_data_dir)
    return env


def _run_inline_python(app_data_dir: Path, code: str, *args) -> subprocess.CompletedProcess[str]:
    app_data_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-c", code, *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=_build_subprocess_env(app_data_dir),
        cwd=ROOT_DIR,
    )
    output = result.stdout + result.stderr
    assert "Traceback" not in output, output
    assert "ModuleNotFoundError" not in output, output
    return result


def _load_last_json_line(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    assert lines, "子进程未输出可解析内容"
    return json.loads(lines[-1])


def test_import_masked_webhook_with_enabled_notify_collects_warnings(tmp_path):
    """脱敏 webhook 无本机同名配置 + 通知启用：告警非空且写明工作流名，DB 中 webhook_id 为 None。"""
    app_data_dir = tmp_path / "masked-app-data"
    payload_path = tmp_path / "masked-import.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": "脱敏机器人",
                        "webhook_url": "__WORKFLOW_WEBHOOK_URL_MASKED__",
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

    result = _run_inline_python(
        app_data_dir,
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

from database import get_workflow_by_name, import_from_json_with_warnings, init_db, list_webhooks

init_db()
result = import_from_json_with_warnings(Path(sys.argv[1]))
workflow = get_workflow_by_name("通知告警工作流")
print(json.dumps({
    "imported_count": result.imported_count,
    "warnings": result.warnings,
    "notify": workflow.get_notify_config() if workflow else None,
    "webhook_count": len(list_webhooks()),
}, ensure_ascii=False))
""",
        payload_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state = _load_last_json_line(result.stdout)

    assert state["imported_count"] == 1
    assert state["warnings"], "导入告警不应为空"
    assert any("通知告警工作流" in warning for warning in state["warnings"])
    assert any("脱敏机器人" in warning for warning in state["warnings"])
    assert any("通知将不会发送" in warning for warning in state["warnings"])
    # 脱敏 webhook 无本机同名配置时不应创建记录
    assert state["webhook_count"] == 0
    # 通知配置保持 enabled，但 webhook_id 为 None（运行期不会发送）
    assert state["notify"]["enabled"] is True
    assert state["notify"]["webhook_id"] is None


def test_import_duplicate_uid_second_time_warns_about_skip(tmp_path):
    """同一 UID 第二次导入：数量为 0 且告警写明跳过。"""
    app_data_dir = tmp_path / "dup-app-data"
    payload_path = tmp_path / "dup-import.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [{"id": "wf_dup_uid", "name": "重复UID工作流"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run_inline_python(
        app_data_dir,
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

from database import import_from_json_with_warnings, init_db

init_db()
first = import_from_json_with_warnings(Path(sys.argv[1]))
second = import_from_json_with_warnings(Path(sys.argv[1]))
print(json.dumps({
    "first_count": first.imported_count,
    "first_warnings": first.warnings,
    "second_count": second.imported_count,
    "second_warnings": second.warnings,
}, ensure_ascii=False))
""",
        payload_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state = _load_last_json_line(result.stdout)

    assert state["first_count"] == 1
    assert state["first_warnings"] == []
    assert state["second_count"] == 0
    assert state["second_warnings"], "重复导入应产生告警"
    assert any("已跳过导入" in warning for warning in state["second_warnings"])
    assert any("重复UID工作流" in warning for warning in state["second_warnings"])
    assert any("wf_dup_uid" in warning for warning in state["second_warnings"])


class _FakeWorkflow:
    """提供 get_notify_config() 的最小工作流替身。"""

    def __init__(self, notify):
        self._notify = notify

    def get_notify_config(self):
        return self._notify


_FAKE_WEBHOOK = SimpleNamespace(
    id=5,
    name="解析测试机器人",
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=secret-token",
    keyword="",
)


def _fake_get_webhook_by_id(webhook_id):
    return _FAKE_WEBHOOK if webhook_id == 5 else None


def test_resolve_target_returns_none_when_disabled_unbound_or_missing():
    cases = [
        {},  # 无配置
        {"enabled": False, "webhook_id": 5},  # 未启用
        {"enabled": True},  # 无 webhook_id
        {"enabled": True, "webhook_id": None},  # webhook_id 为 None
        {"enabled": True, "webhook_id": 404},  # 机器人不存在
    ]

    for notify in cases:
        target = notifier.resolve_workflow_notification_target(
            _FakeWorkflow(notify), _fake_get_webhook_by_id
        )
        assert target is None, f"notify={notify!r} 应解析为 None"


def test_resolve_target_returns_webhook_and_template_when_configured():
    target = notifier.resolve_workflow_notification_target(
        _FakeWorkflow({"enabled": True, "webhook_id": 5}), _fake_get_webhook_by_id
    )

    assert target is not None
    webhook, template = target
    assert webhook is _FAKE_WEBHOOK
    assert template == notifier.DEFAULT_NOTIFY_MESSAGE_TEMPLATE

    custom = notifier.resolve_workflow_notification_target(
        _FakeWorkflow({"enabled": True, "webhook_id": 5, "message_template": "自定义 {状态}"}),
        _fake_get_webhook_by_id,
    )

    assert custom == (_FAKE_WEBHOOK, "自定义 {状态}")


def test_default_template_matches_engine_core_notification_source():
    """L2: 默认模板以 notifier 为权威定义，必须与 engine_core/notification.py 中的字面量一致。"""
    assert notifier.DEFAULT_NOTIFY_MESSAGE_TEMPLATE == "{工作流名称} - {状态} - 编号={运行编号}"

    engine_core_source = (SRC_DIR / "engine_core" / "notification.py").read_text(encoding="utf-8")
    assert notifier.DEFAULT_NOTIFY_MESSAGE_TEMPLATE in engine_core_source

    cli_source = (SRC_DIR / "cli.py").read_text(encoding="utf-8")
    assert "resolve_workflow_notification_target" in cli_source


def test_import_export_round_trip_preserves_step_output_paths(tmp_path):
    """ROI-2: 步骤显式输出声明在 导入→落库→导出 全链路保持不变；旧 JSON 缺省该字段同样可导入。"""
    app_data_dir = tmp_path / "output-paths-app-data"
    payload_path = tmp_path / "output-paths-import.json"
    export_path = tmp_path / "output-paths-export.json"
    declared = ["D:/数据/基础文件", "D:/数据/报表/月报.xlsx"]
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_output_paths",
                        "name": "输出声明工作流",
                        "steps": [
                            {
                                "id": "step_declared",
                                "name": "声明输出步骤",
                                "step_type": "python",
                                "script": "refresh.py",
                                "output_paths": declared,
                            },
                            {
                                # 旧版导出 JSON 不带 output_paths 字段，必须照常导入
                                "id": "step_legacy",
                                "name": "旧字段步骤",
                                "step_type": "python",
                                "script": "legacy.py",
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run_inline_python(
        app_data_dir,
        """
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "src"))

from database import (
    export_to_json,
    get_steps_by_workflow,
    get_workflow_by_uid,
    import_from_json_with_warnings,
    init_db,
)

init_db()
imported = import_from_json_with_warnings(Path(sys.argv[1]))
workflow = get_workflow_by_uid("wf_output_paths")
steps = {step.uid: step for step in get_steps_by_workflow(workflow.id)}
export_to_json(Path(sys.argv[2]), workflow_ids=[workflow.id])
exported = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
exported_steps = {step["id"]: step for step in exported["workflows"][0]["steps"]}
print(json.dumps({
    "imported_count": imported.imported_count,
    "db_declared": steps["step_declared"].get_output_paths(),
    "db_legacy": steps["step_legacy"].get_output_paths(),
    "exported_declared": exported_steps["step_declared"]["output_paths"],
    "exported_legacy": exported_steps["step_legacy"]["output_paths"],
}, ensure_ascii=False))
""",
        payload_path,
        export_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state = _load_last_json_line(result.stdout)

    assert state["imported_count"] == 1
    # 导入落库：声明字段写入 Step.output_paths；缺省字段保持空声明
    assert state["db_declared"] == declared
    assert state["db_legacy"] == []
    # 导出：声明原样回写；未声明步骤导出空数组（可选字段，schema version 不变）
    assert state["exported_declared"] == declared
    assert state["exported_legacy"] == []
