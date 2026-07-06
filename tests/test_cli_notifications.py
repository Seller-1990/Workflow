# -*- coding: utf-8 -*-
"""CLI notification helper tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cli_notifications


def test_send_cli_notification_formats_error_summary(monkeypatch):
    sent = {}
    output = []
    workflow = SimpleNamespace(name="日报", uid="wf-1")
    webhook = SimpleNamespace(webhook_url="https://example.test", keyword="", name="机器人")

    monkeypatch.setattr(
        "notifier.resolve_workflow_notification_target",
        lambda _workflow, _get_webhook_by_id: (webhook, "{工作流名称}"),
    )

    def fake_send_workflow_notification(**kwargs):
        sent.update(kwargs)
        return True, "ok"

    monkeypatch.setattr("notifier.send_workflow_notification", fake_send_workflow_notification)

    cli_notifications.send_cli_notification(
        workflow=workflow,
        success=False,
        notify_on_complete=False,
        notify_on_error=True,
        error_messages=[{"step_name": "下载", "error_message": "timeout"}],
        print_func=output.append,
    )

    assert sent["status"] == "failure"
    assert sent["failure_summary"] == "下载: timeout"
    assert output == ["[通知] 已发送运行状态通知到【机器人】"]


def test_send_cli_notification_skips_when_policy_disabled(monkeypatch):
    called = False

    def fake_resolve(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("notifier.resolve_workflow_notification_target", fake_resolve)

    cli_notifications.send_cli_notification(
        workflow=SimpleNamespace(name="日报", uid="wf-1"),
        success=True,
        notify_on_complete=False,
        notify_on_error=True,
    )

    assert called is False
