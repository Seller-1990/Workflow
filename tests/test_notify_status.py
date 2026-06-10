# -*- coding: utf-8 -*-
"""通知结果回写（run_histories.notify_status）测试

覆盖 engine_core.notification.send_run_notification 的回写矩阵：
sent / failed / skipped 三态、250 字符截断、回写失败不打断通知流程、
以及 run_history_id 缺省时按 run_id 反查真实数据库行。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
import engine_core.notification as notification_module
from engine_core.notification import send_run_notification


class FakeWorkflow:
    """提供 get_notify_config / name / uid 的最小工作流替身"""

    def __init__(self, notify_config):
        self._notify_config = notify_config
        self.name = "测试工作流"
        self.uid = "wf_notify_status"

    def get_notify_config(self):
        return self._notify_config


FAKE_WEBHOOK = SimpleNamespace(
    id=5,
    name="测试机器人",
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=test-token",
    keyword="",
)


def _call_send(workflow, logs, *, run_id="run-001", **kwargs):
    send_run_notification(
        workflow,
        run_id=run_id,
        status="success",
        log_dir="logs/run-001",
        reason="manual",
        start_time=datetime(2026, 6, 10, 8, 0, 0),
        end_time=datetime(2026, 6, 10, 8, 0, 30),
        log_cb=logs.append,
        **kwargs,
    )


def _install_recorder(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        database,
        "update_run_history",
        lambda run_history_id, **fields: recorded.append((run_history_id, fields)),
    )
    return recorded


def test_notify_status_recorded_as_sent_on_success(monkeypatch):
    recorded = _install_recorder(monkeypatch)
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)
    monkeypatch.setattr(
        notification_module, "send_workflow_notification", lambda **_kwargs: (True, "发送成功")
    )

    logs = []
    _call_send(FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_history_id=77)

    assert recorded == [(77, {"notify_status": "sent"})]
    assert logs == ["已发送钉钉通知到【测试机器人】"]


def test_notify_status_recorded_as_failed_with_message(monkeypatch):
    recorded = _install_recorder(monkeypatch)
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)
    monkeypatch.setattr(
        notification_module,
        "send_workflow_notification",
        lambda **_kwargs: (False, "发送失败: token 无效"),
    )

    logs = []
    _call_send(FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_history_id=77)

    assert len(recorded) == 1
    assert recorded[0][0] == 77
    value = recorded[0][1]["notify_status"]
    assert value.startswith("failed:")
    assert "token 无效" in value
    assert logs == ["钉钉通知发送失败: 发送失败: token 无效"]


def test_notify_status_failure_message_truncated_to_250_chars(monkeypatch):
    recorded = _install_recorder(monkeypatch)
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)
    monkeypatch.setattr(
        notification_module,
        "send_workflow_notification",
        lambda **_kwargs: (False, "x" * 500),
    )

    logs = []
    _call_send(FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_history_id=77)

    value = recorded[0][1]["notify_status"]
    assert value.startswith("failed:")
    assert len(value) == 250


def test_notify_status_recorded_as_skipped_when_disabled(monkeypatch):
    recorded = _install_recorder(monkeypatch)
    sent = []
    monkeypatch.setattr(
        notification_module,
        "send_workflow_notification",
        lambda **kwargs: sent.append(kwargs) or (True, "发送成功"),
    )

    logs = []
    _call_send(FakeWorkflow({"enabled": False, "webhook_id": 5}), logs, run_history_id=77)

    assert recorded == [(77, {"notify_status": "skipped: 未启用"})]
    assert logs == []  # 未启用时保持原行为：静默返回
    assert sent == []


def test_notify_status_recorded_as_skipped_when_webhook_unbound(monkeypatch):
    recorded = _install_recorder(monkeypatch)

    logs = []
    _call_send(FakeWorkflow({"enabled": True}), logs, run_history_id=77)

    assert recorded == [(77, {"notify_status": "skipped: 未配置机器人"})]
    assert logs == ["通知未配置机器人"]


def test_notify_status_recorded_as_failed_when_webhook_missing(monkeypatch):
    recorded = _install_recorder(monkeypatch)
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: None)

    logs = []
    _call_send(FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_history_id=77)

    assert recorded == [(77, {"notify_status": "failed: 未找到机器人配置: 5"})]
    assert logs == ["未找到机器人配置: 5"]


def test_notify_status_recorded_as_failed_when_send_raises(monkeypatch):
    recorded = _install_recorder(monkeypatch)
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)

    def _boom(**_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(notification_module, "send_workflow_notification", _boom)

    logs = []
    _call_send(FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_history_id=77)

    assert len(recorded) == 1
    value = recorded[0][1]["notify_status"]
    assert value.startswith("failed:")
    assert "network down" in value
    assert logs == ["发送通知出错: network down"]


def test_record_failure_never_breaks_notification(monkeypatch, caplog):
    monkeypatch.setattr(
        database,
        "update_run_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db locked")),
    )
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)
    monkeypatch.setattr(
        notification_module, "send_workflow_notification", lambda **_kwargs: (True, "发送成功")
    )

    logs = []
    with caplog.at_level(logging.WARNING, logger="engine_core.notification"):
        _call_send(FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_history_id=77)

    # 回写失败被吞掉：通知本身照常成功，只留 warning 日志
    assert logs == ["已发送钉钉通知到【测试机器人】"]
    assert "通知状态回写失败" in caplog.text
    assert "db locked" in caplog.text


def _use_temp_database(monkeypatch, tmp_path: Path):
    """复用 test_schema_guards 的进程内临时库隔离模式"""
    database.cleanup_session()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workflows.db")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_SessionFactory", None)
    monkeypatch.setattr(database, "_scoped_session", None)
    monkeypatch.setattr(database, "_init_done", False)
    database.init_db()
    return database


def test_run_history_id_resolved_by_run_id_when_missing(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("通知回写反查")
    run_history = db.create_run_history(workflow.id, reason="manual")

    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)
    monkeypatch.setattr(
        notification_module, "send_workflow_notification", lambda **_kwargs: (True, "发送成功")
    )

    logs = []
    # 不传 run_history_id（engine.py 现有调用方式）→ 走 run_id 反查 + 真实写库
    _call_send(
        FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_id=run_history.run_id
    )

    stored = db.get_latest_run_history(workflow.id)
    assert stored.id == run_history.id
    assert stored.notify_status == "sent"
    assert logs == ["已发送钉钉通知到【测试机器人】"]


def test_record_skips_quietly_when_run_id_not_found(monkeypatch, tmp_path, caplog):
    _use_temp_database(monkeypatch, tmp_path)
    monkeypatch.setattr(notification_module, "get_webhook_by_id", lambda _id: FAKE_WEBHOOK)
    monkeypatch.setattr(
        notification_module, "send_workflow_notification", lambda **_kwargs: (True, "发送成功")
    )

    logs = []
    with caplog.at_level(logging.WARNING, logger="engine_core.notification"):
        _call_send(
            FakeWorkflow({"enabled": True, "webhook_id": 5}), logs, run_id="run-not-exist"
        )

    assert logs == ["已发送钉钉通知到【测试机器人】"]
    assert "跳过通知状态回写" in caplog.text
