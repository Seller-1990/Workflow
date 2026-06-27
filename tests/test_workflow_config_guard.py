# -*- coding: utf-8 -*-
"""工作流监听配置防呆测试"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication

import ui.workflow_config as workflow_config_module
from ui.workflow_config import WorkflowConfigPanel
from watch_rules import detect_watch_output_conflicts


@dataclass
class MockStep:
    script_path: str | None = None

    def get_args(self) -> list[str]:
        return []


def test_detect_watch_output_conflicts_flags_monthly_workflow_output_dirs():
    conflicts = detect_watch_output_conflicts(
        [
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表",
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/月度接收/1账务信息/2026",
        ],
        [
            MockStep(
                script_path=(
                    "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/计算脚本/"
                    "01_月度数据处理/00_月度接收/00_月度接收__月度基础数据刷新.py"
                )
            )
        ],
    )

    assert "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\基础文件\\收入成本表" in conflicts
    assert all("月度接收" not in item for item in conflicts)


def test_detect_watch_output_conflicts_allows_monthly_workflow_input_dir():
    conflicts = detect_watch_output_conflicts(
        ["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/月度接收/1账务信息/2026"],
        [
            MockStep(
                script_path=(
                    "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/计算脚本/"
                    "01_月度数据处理/00_月度接收/00_月度接收__月度基础数据刷新.py"
                )
            )
        ],
    )

    assert conflicts == []


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
            "watch_enabled": False,
            "watch_mode": "any_change",
            "cooldown_seconds": 8,
            "settle_seconds": 15,
            "get_notify_config": lambda self: {"enabled": False, "webhook_id": None, "message_template": "tpl"},
            "get_watch_folders": lambda self: [],
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
