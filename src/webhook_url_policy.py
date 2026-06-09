# -*- coding: utf-8 -*-
"""Webhook URL trust-boundary helpers.

Centralizes DingTalk webhook validation and redacted logging so import,
CRUD, and outbound notifier paths use the same policy.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse


DINGTALK_WEBHOOK_HOST = "oapi.dingtalk.com"
DINGTALK_WEBHOOK_PATH = "/robot/send"


def is_masked_webhook_url(value: str | None, masked_value: str) -> bool:
    """Return whether an imported webhook URL is an explicit masked placeholder."""
    text = (value or "").strip()
    if not text:
        return False
    return text == masked_value or text.lower() in {"<masked>", "masked", "***"}


def is_valid_dingtalk_webhook_url(value: str | None) -> bool:
    """Validate an outbound DingTalk robot webhook URL.

    The policy intentionally rejects non-HTTPS schemes, look-alike hosts, wrong
    paths, and empty access tokens before any network request is attempted.
    """
    text = (value or "").strip()
    if not text:
        return False
    try:
        result = urlparse(text)
    except Exception:
        return False
    if result.scheme != "https" or result.netloc.lower() != DINGTALK_WEBHOOK_HOST:
        return False
    if result.path.rstrip("/") != DINGTALK_WEBHOOK_PATH:
        return False
    token_values = parse_qs(result.query).get("access_token", [])
    return any(token.strip() for token in token_values)


def mask_webhook_url_for_log(value: str | None) -> str:
    """Return a safe URL summary that never exposes access_token."""
    text = (value or "").strip()
    if not text:
        return "<empty>"
    try:
        result = urlparse(text)
    except Exception:
        return "<invalid-url>"
    host = result.netloc or "<no-host>"
    path = result.path or ""
    return f"{result.scheme}://{host}{path}?access_token=<redacted>"
