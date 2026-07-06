# -*- coding: utf-8 -*-
"""Pure import/export security guards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

MASKED_WEBHOOK_PLACEHOLDER = "__WORKFLOW_WEBHOOK_URL_MASKED__"


def assert_no_plain_webhook_secrets(payload: object) -> None:
    """Reject exported payloads that still contain plain DingTalk tokens."""
    leaks: list[str] = []
    _collect_plain_webhook_secret_paths(payload, "$", leaks)
    if leaks:
        joined = "；".join(leaks)
        raise ValueError(f"导出 payload 包含未脱敏 Webhook access_token: {joined}")


def _collect_plain_webhook_secret_paths(value: object, path: str, leaks: list[str]) -> None:
    if isinstance(value, str):
        if value != MASKED_WEBHOOK_PLACEHOLDER and "access_token=" in value:
            leaks.append(path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _collect_plain_webhook_secret_paths(item, f"{path}.{key}", leaks)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for index, item in enumerate(value):
            _collect_plain_webhook_secret_paths(item, f"{path}[{index}]", leaks)
