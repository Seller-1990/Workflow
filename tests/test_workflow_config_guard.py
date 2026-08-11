# -*- coding: utf-8 -*-
"""工作流配置防呆测试"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication

import ui.workflow_config as workflow_config_module
from ui.workflow_config import WorkflowConfigPanel


def test_workflow_config_dirty_state_tracks_user_edits_and_save(monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved = []
    workflow = type(
        "Workflow",
        (),
        {
            "name": "月报流程",
            "chart_theme": "default",
            "parallel_enabled": True,
            "max_workers": 3,
            "get_notify_config": lambda self: {"enabled": False, "webhook_id": None, "message_template": "tpl"},
        },
    )()
    monkeypatch.setattr(workflow_config_module, "get_workflow_by_id", lambda workflow_id: workflow)
    monkeypatch.setattr(workflow_config_module, "list_webhooks", lambda: [])
    monkeypatch.setattr(workflow_config_module, "update_workflow", lambda workflow_id, **kwargs: saved.append((workflow_id, kwargs)))
    panel = WorkflowConfigPanel()
    try:
        panel.load_workflow(11)
        assert panel.is_dirty() is False

        panel.edit_name.setText("月报流程-已改")
        assert panel.is_dirty() is True

        messages = []
        panel.statusbar = type(
            "StatusBar",
            (),
            {"showMessage": lambda self, message, timeout: messages.append((message, timeout))},
        )()

        assert panel.save_config() is True
        assert panel.is_dirty() is False
        assert saved[0][0] == 11
        assert messages == [("配置已保存", 2000)]

        monkeypatch.setattr(
            workflow_config_module,
            "list_webhooks",
            lambda: [type("Webhook", (), {"id": 3, "name": "通知机器人", "keyword": "财务"})()],
        )
        panel.refresh_webhooks()
        assert panel.is_dirty() is False
    finally:
        panel.deleteLater()
        assert app is not None
