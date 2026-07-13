# -*- coding: utf-8 -*-
"""DingTalk notifier behavior tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import notifier


def test_send_dingtalk_message_uses_existing_ca_bundle(monkeypatch, tmp_path):
    ca_bundle = tmp_path / "cacert.pem"
    ca_bundle.write_text("test-ca", encoding="utf-8")
    captured = {}

    class Response:
        status_code = 200
        text = '{"errcode": 0}'

        def json(self):
            return {"errcode": 0}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(notifier, "resolve_ca_bundle", lambda: ca_bundle)
    monkeypatch.setattr(notifier.requests, "post", fake_post)

    ok, message = notifier.send_dingtalk_message(
        "https://oapi.dingtalk.com/robot/send?access_token=test-token",
        "hello",
    )

    assert ok is True
    assert message == "发送成功"
    assert captured["verify"] == str(ca_bundle)


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

    ok, message = notifier.send_dingtalk_message("https://oapi.dingtalk.com/robot/send?access_token=test-token", "hello")

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

    ok, message = notifier.send_dingtalk_message("https://oapi.dingtalk.com/robot/send?access_token=test-token", "hello")

    assert ok is False
    assert message == "发送失败: HTTP 403: invalid token"


def test_send_dingtalk_message_reports_missing_ca_bundle(monkeypatch):
    def _raise_missing_ca_bundle(*_args, **_kwargs):
        raise OSError(
            r"Could not find a suitable TLS CA certificate bundle, invalid path: C:\Temp\_MEI1\certifi\cacert.pem"
        )

    monkeypatch.setattr(notifier.requests, "post", _raise_missing_ca_bundle)

    ok, message = notifier.send_dingtalk_message("https://oapi.dingtalk.com/robot/send?access_token=test-token", "hello")

    assert ok is False
    assert "TLS CA 证书文件缺失或路径无效" in message
    assert "certifi/cacert.pem" in message



def test_send_dingtalk_message_rejects_untrusted_webhook_before_network(monkeypatch):
    called = False

    def _post(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be called for invalid webhook URLs")

    monkeypatch.setattr(notifier.requests, "post", _post)

    ok, message = notifier.send_dingtalk_message("http://127.0.0.1/robot/send?access_token=secret-token", "hello")

    assert ok is False
    assert called is False
    assert "Webhook URL 非法或不受信任" in message
    assert "secret-token" not in message
    assert "access_token=<redacted>" in message


def test_send_dingtalk_message_redacts_access_token_in_request_exception(monkeypatch):
    def _post(*_args, **_kwargs):
        raise RuntimeError("boom https://oapi.dingtalk.com/robot/send?access_token=secret-token")

    monkeypatch.setattr(notifier.requests, "post", _post)

    ok, message = notifier.send_dingtalk_message(
        "https://oapi.dingtalk.com/robot/send?access_token=request-token",
        "hello",
    )

    assert ok is False
    assert "secret-token" not in message
    assert "request-token" not in message
    assert "access_token=<redacted>" in message


def test_send_dingtalk_message_redacts_access_token_in_http_json_errmsg(monkeypatch):
    leaked = "bad https://oapi.dingtalk.com/robot/send?access_token=provider-token"
    monkeypatch.setattr(
        notifier.requests,
        "post",
        lambda *args, **kwargs: _Response(403, '{"errmsg":"bad"}', {"errcode": 40001, "errmsg": leaked}),
    )

    ok, message = notifier.send_dingtalk_message(
        "https://oapi.dingtalk.com/robot/send?access_token=request-token",
        "hello",
    )

    assert ok is False
    assert "provider-token" not in message
    assert "request-token" not in message
    assert "access_token=<redacted>" in message


def test_send_dingtalk_message_redacts_access_token_in_business_json_errmsg(monkeypatch):
    leaked = "invalid access_token=https://oapi.dingtalk.com/robot/send?access_token=provider-token"
    monkeypatch.setattr(
        notifier.requests,
        "post",
        lambda *args, **kwargs: _Response(200, '{"errmsg":"bad"}', {"errcode": 40001, "errmsg": leaked}),
    )

    ok, message = notifier.send_dingtalk_message(
        "https://oapi.dingtalk.com/robot/send?access_token=request-token",
        "hello",
    )

    assert ok is False
    assert "provider-token" not in message
    assert "request-token" not in message
    assert "access_token=<redacted>" in message
