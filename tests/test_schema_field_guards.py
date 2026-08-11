# -*- coding: utf-8 -*-
"""模式字段守卫测试：更新字段白名单与导入字段类型校验。"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _schema_guard_utils import _use_temp_database


def test_import_rejects_unsupported_step_type(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad_step_type.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad_step_type",
                        "name": "非法步骤类型",
                        "steps": [
                            {
                                "id": "step_bad",
                                "name": "Bad",
                                "step_type": "cmd_shell",
                                "script": "calc.exe",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.workflows\[0\]\.steps\[0\]\.step_type"):
        db.import_from_json(payload_path)


def test_import_ignores_retired_config_fields(monkeypatch, tmp_path: Path):
    """退役字段(watch / single_script)允许存在于旧 JSON 但被明确忽略,不做形状校验。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "retired-fields.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_retired",
                        "name": "退役字段",
                        "watch": {
                            "enabled": True,
                            "mode": "unsupported-mode",
                            "folders": ["D:/ok", 99],
                        },
                        "single_script": {
                            "enabled": True,
                            "type": "cmd_shell",
                            "path": 123,
                        },
                        "steps": [{"name": "A", "step_type": "python", "script": "job.py"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert db.import_from_json(payload_path) == 1


def test_create_and_update_webhook_reject_non_dingtalk_urls(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="Webhook URL 必须是钉钉机器人"):
        db.create_webhook("外部地址", "https://example.com/robot/send?access_token=local-token")

    webhook = db.create_webhook(
        "财务机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=local-token",
    )

    with pytest.raises(ValueError, match="Webhook URL 必须是钉钉机器人"):
        db.update_webhook(webhook.id, webhook_url="http://oapi.dingtalk.com/robot/send?access_token=abc")


def test_create_and_update_webhook_reject_duplicate_names(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    first = db.create_webhook(
        "财务机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=local-token",
    )
    second = db.create_webhook(
        "研发机器人",
        "https://oapi.dingtalk.com/robot/send?access_token=dev-token",
    )

    with pytest.raises(ValueError, match="Webhook 名称已存在: 财务机器人"):
        db.create_webhook(
            " 财务机器人 ",
            "https://oapi.dingtalk.com/robot/send?access_token=other-token",
        )

    with pytest.raises(ValueError, match="Webhook 名称已存在: 财务机器人"):
        db.update_webhook(second.id, name=first.name)


def test_import_rejects_non_dingtalk_webhook_url(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-webhook.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": "恶意地址",
                        "webhook_url": "https://example.com/collect?access_token=local-token",
                    }
                ],
                "workflows": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Webhook URL 必须是钉钉机器人地址"):
        db.import_from_json(payload_path)


def test_import_reports_schema_path_for_bad_webhook_field_type(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-webhook-field.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "webhooks": [
                    {
                        "name": ["财务机器人"],
                        "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token",
                    }
                ],
                "workflows": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.webhooks\[0\]\.name"):
        db.import_from_json(payload_path)


@pytest.mark.parametrize(
    ("field", "value", "expected_path"),
    [
        ("id", 123, r"\$\.workflows\[0\]\.id"),
        ("name", ["坏名字"], r"\$\.workflows\[0\]\.name"),
        ("description", {"bad": "type"}, r"\$\.workflows\[0\]\.description"),
        ("steps[0].id", 456, r"\$\.workflows\[0\]\.steps\[0\]\.id"),
        ("steps[0].name", {"bad": "type"}, r"\$\.workflows\[0\]\.steps\[0\]\.name"),
        ("steps[0].stage_uid", 789, r"\$\.workflows\[0\]\.steps\[0\]\.stage_uid"),
        ("steps[0].step_type", True, r"\$\.workflows\[0\]\.steps\[0\]\.step_type"),
        ("steps[0].script", {"bad": "type"}, r"\$\.workflows\[0\]\.steps\[0\]\.script"),
        ("steps[0].cwd", 3.14, r"\$\.workflows\[0\]\.steps\[0\]\.cwd"),
    ],
)
def test_import_reports_schema_path_for_string_field_type_errors(monkeypatch, tmp_path: Path, field, value, expected_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload = {
        "version": 1,
        "workflows": [
            {
                "id": "wf_bad_string",
                "name": "坏字段",
                "description": "ok",
                "single_script": {
                    "enabled": True,
                    "type": "python",
                    "path": "job.py",
                    "cwd": "jobs",
                },
                "steps": [
                    {
                        "id": "step_1",
                        "name": "步骤A",
                        "stage_uid": "stage_1",
                        "step_type": "python",
                        "script": "job.py",
                        "cwd": "jobs",
                    }
                ],
            }
        ],
    }

    current = payload["workflows"][0]
    parts = field.replace("]", "").split(".")
    for part in parts[:-1]:
        if "[" in part:
            key, index = part.split("[")
            current = current[key][int(index)]
        else:
            current = current[part]
    leaf = parts[-1]
    if "[" in leaf:
        key, index = leaf.split("[")
        current[key][int(index)] = value
    else:
        current[leaf] = value

    payload_path = tmp_path / "bad-string-field.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_path):
        db.import_from_json(payload_path)


def test_json_import_reports_schema_path_for_bad_boolean(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-schema.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad",
                        "name": "坏结构",
                        "steps": [{"name": "A", "skip_on_success": "false"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.workflows\[0\]\.steps\[0\]\.skip_on_success"):
        db.import_from_json(payload_path)


def test_json_import_rejects_non_list_saved_run_args(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-saved-run-args.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad_saved_args",
                        "name": "坏运行参数",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "步骤A",
                                "saved_run_args": "--year 2026",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"\$\.workflows\[0\]\.steps\[0\]\.saved_run_args",
    ):
        db.import_from_json(payload_path)


def test_json_import_rejects_non_string_saved_run_arg_item(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-saved-run-arg-item.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad_saved_arg_item",
                        "name": "坏运行参数项",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "步骤A",
                                "saved_run_args": ["--year", 2026],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"\$\.workflows\[0\]\.steps\[0\]\.saved_run_args\[1\]",
    ):
        db.import_from_json(payload_path)


def test_json_import_rejects_bad_notify_field_types(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-notify.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad_notify",
                        "name": "坏通知",
                        "notify": {"enabled": "yes", "message_template": ["bad"]},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.workflows\[0\]\.notify\.enabled"):
        db.import_from_json(payload_path)


def test_json_import_rejects_bad_notify_json_string(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-notify-string.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad_notify_string",
                        "name": "坏通知字符串",
                        "notify": json.dumps({"enabled": True, "extra": "unexpected"}),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.workflows\[0\]\.notify\.extra"):
        db.import_from_json(payload_path)


def test_json_import_rejects_legacy_notify_fields(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "legacy-notify.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_legacy_notify",
                        "name": "旧通知字段",
                        "notify": {
                            "enabled": True,
                            "ding_talk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=token",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.workflows\[0\]\.notify\.ding_talk_webhook"):
        db.import_from_json(payload_path)


def test_json_import_ignores_bad_watch_config(monkeypatch, tmp_path: Path):
    """退役 watch 字段即使形状非法也忽略(旧 JSON 兼容),不报错。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "bad-watch.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_bad_watch",
                        "name": "坏监听",
                        "watch": {"mode": 123, "folders": ["D:/ok", 99]},
                        "steps": [{"name": "A", "step_type": "python", "script": "job.py"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert db.import_from_json(payload_path) == 1


def test_json_import_rejects_unsupported_version(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "future-version.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 999,
                "workflows": [{"id": "future", "name": "未来格式"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.version"):
        db.import_from_json(payload_path)


def test_json_import_rejects_missing_version(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "missing-version.json"
    payload_path.write_text(
        json.dumps({"workflows": [{"id": "missing", "name": "缺版本"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"\$\.version"):
        db.import_from_json(payload_path)


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
