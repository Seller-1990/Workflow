# -*- coding: utf-8 -*-
"""本地真实外设集成测试（默认全部跳过，按环境变量显式开启）。

背景：仓库内既有测试对钉钉网络全部使用 mock，真实外设路径（真实发送钉钉
消息）此前只能在生产环境验证。本模块补上这一层 OPT-IN 的本地集成测试：
CI 与未设置环境变量的本地运行自动跳过，不影响质量门；需要验证真实外设时
按下述方式显式开启。

激活方式（Windows cmd）：

- 真实钉钉发送测试（会真实发送一条消息到目标机器人）::

    set WORKFLOW_TEST_DINGTALK_WEBHOOK=<真实机器人URL>
    rem 可选：机器人安全设置为「自定义关键词」时提供
    set WORKFLOW_TEST_DINGTALK_WEBHOOK_KEYWORD=<关键词>
    python -m pytest tests/test_local_integration.py -m local_integration -q

注意：

- Webhook URL 必须是 ``https://oapi.dingtalk.com/robot/send`` 下的真实机器人
  地址，``src/webhook_url_policy.py`` 会拒绝其他主机或非 HTTPS 地址。
- 本文件不得硬编码任何 access_token 残留（``tools/repo_hygiene.py`` 会扫描
  tests/ 目录），真实地址只允许通过环境变量注入，不落盘。
- 本文件不得新增 broad except（``tools/audit_broad_except.py`` 对 tests/ 同样
  生效且 baseline 中没有本文件的豁免条目）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import notifier

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.local_integration
@pytest.mark.skipif(
    not os.environ.get("WORKFLOW_TEST_DINGTALK_WEBHOOK"),
    reason="未设置 WORKFLOW_TEST_DINGTALK_WEBHOOK，默认跳过真实钉钉发送测试",
)
def test_dingtalk_real_send():
    """真实钉钉发送：向环境变量提供的机器人真实发送一条集成测试消息。"""
    url = os.environ["WORKFLOW_TEST_DINGTALK_WEBHOOK"]
    keyword = os.environ.get("WORKFLOW_TEST_DINGTALK_WEBHOOK_KEYWORD", "")

    ok, message = notifier.send_dingtalk_message(
        url,
        "【集成测试】Workflow 本地集成测试消息",
        keyword=keyword,
    )

    # send_dingtalk_message 返回的 message 已做 access_token 脱敏，可安全展示
    assert ok is True, f"真实钉钉发送失败: {message}"


@pytest.mark.local_integration
def test_local_integration_marker_registered_in_pytest_ini():
    """廉价 wiring 自检（CI 中照常执行）：marker 必须已在 pytest.ini 注册。

    防止 pytest.ini 的 markers 注册被误删导致本层测试退化为未注册 marker。
    """
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "markers" in text, "pytest.ini 缺少 markers 配置段"
    assert "local_integration:" in text, "pytest.ini 未注册 local_integration marker"
    assert "默认跳过" in text, "local_integration marker 描述应注明默认跳过"
