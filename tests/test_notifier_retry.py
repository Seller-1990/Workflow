# -*- coding: utf-8 -*-
"""send_workflow_notification 瞬时失败重试行为测试."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import notifier


def _send_notification():
    return notifier.send_workflow_notification(
        webhook_url="https://oapi.dingtalk.com/robot/send?access_token=t",
        keyword="",
        template="{状态}",
        workflow_name="wf",
        workflow_uid="u",
        status="success",
        run_id="r1",
    )


def test_transient_failure_retries_once_and_returns_second_result(monkeypatch):
    monkeypatch.setattr(notifier, "NOTIFY_TRANSIENT_RETRY_DELAY_SECONDS", 0)
    calls = []

    def _fake_send(webhook_url, message, keyword=""):
        calls.append((webhook_url, message, keyword))
        if len(calls) == 1:
            return False, "请求超时"
        return True, "发送成功"

    monkeypatch.setattr(notifier, "send_dingtalk_message", _fake_send)

    ok, msg = _send_notification()

    assert (ok, msg) == (True, "发送成功")
    assert len(calls) == 2


def test_non_transient_failure_returns_immediately_without_retry(monkeypatch):
    monkeypatch.setattr(notifier, "NOTIFY_TRANSIENT_RETRY_DELAY_SECONDS", 0)
    calls = []

    def _fake_send(webhook_url, message, keyword=""):
        calls.append((webhook_url, message, keyword))
        return False, "发送失败: token 无效"

    monkeypatch.setattr(notifier, "send_dingtalk_message", _fake_send)

    ok, msg = _send_notification()

    assert ok is False
    assert msg == "发送失败: token 无效"
    assert len(calls) == 1
