# -*- coding: utf-8 -*-
"""DingTalk notifier behavior tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import notifier


class _Response:
    def __init__(self, status_code: int, text: str, payload=None, json_error: Exception | None = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


def test_send_dingtalk_message_reports_non_json_http_context(monkeypatch):
    monkeypatch.setattr(
        notifier.requests,
        "post",
        lambda *args, **kwargs: _Response(502, "<html>bad gateway</html>", json_error=ValueError("not json")),
    )

    ok, message = notifier.send_dingtalk_message("https://example.test/hook", "hello")

    assert ok is False
    assert "HTTP 502" in message
    assert "响应不是 JSON" in message
    assert "bad gateway" in message


def test_send_dingtalk_message_reports_http_error_with_provider_message(monkeypatch):
    monkeypatch.setattr(
        notifier.requests,
        "post",
        lambda *args, **kwargs: _Response(403, '{"errmsg":"invalid token"}', {"errcode": 40001, "errmsg": "invalid token"}),
    )

    ok, message = notifier.send_dingtalk_message("https://example.test/hook", "hello")

    assert ok is False
    assert message == "发送失败: HTTP 403: invalid token"
