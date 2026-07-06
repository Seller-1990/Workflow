# -*- coding: utf-8 -*-
"""导入导出安全边界纯单元测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from import_export_security import (
    MASKED_WEBHOOK_PLACEHOLDER,
    assert_no_plain_webhook_secrets,
)


def test_assert_no_plain_webhook_secrets_allows_masked_placeholder():
    assert_no_plain_webhook_secrets(
        {
            "webhooks": [
                {
                    "webhook_url": MASKED_WEBHOOK_PLACEHOLDER,
                    "webhook_url_masked": True,
                }
            ]
        }
    )


def test_assert_no_plain_webhook_secrets_rejects_nested_access_token():
    with pytest.raises(ValueError, match=r"\$\.webhooks\[0\]\.webhook_url"):
        assert_no_plain_webhook_secrets(
            {
                "webhooks": [
                    {
                        "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=secret",
                    }
                ]
            }
        )
