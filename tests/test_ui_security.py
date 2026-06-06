# -*- coding: utf-8 -*-
"""UI 安全与确认交互测试"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

import ui.step_editor as step_editor_module
import ui.webhook_manager as webhook_manager_module
from ui.step_editor import StepEditorPanel
from ui.webhook_manager import WebhookManagerDialog


def test_webhook_url_is_masked_by_default_and_can_be_revealed(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])
    dialog = WebhookManagerDialog()
    try:
        assert dialog.edit_url.echoMode() == QLineEdit.Password

        dialog.btn_toggle_url.setChecked(True)

        assert dialog.edit_url.echoMode() == QLineEdit.Normal
        assert dialog.btn_toggle_url.text() == "隐藏"

        dialog.btn_toggle_url.setChecked(False)

        assert dialog.edit_url.echoMode() == QLineEdit.Password
        assert dialog.btn_toggle_url.text() == "显示"
    finally:
        dialog.close()
        assert app is not None


def test_webhook_url_validation_requires_dingtalk_robot_endpoint(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])
    dialog = WebhookManagerDialog()
    try:
        assert dialog._validate_webhook_url(
            "https://oapi.dingtalk.com/robot/send?access_token=abcDEF123456"
        )
        assert not dialog._validate_webhook_url("https://example.com/robot/send?access_token=abcDEF123456")
        assert not dialog._validate_webhook_url("http://oapi.dingtalk.com/robot/send?access_token=abcDEF123456")
        assert not dialog._validate_webhook_url("https://oapi.dingtalk.com/robot/send")
        assert not dialog._validate_webhook_url("https://oapi.dingtalk.com/robot/send?access_token=")
    finally:
        dialog.close()
        assert app is not None


def test_step_editor_blocks_missing_script_path_when_user_cancels(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = StepEditorPanel()
    update_calls = []
    try:
        panel._step_id = 1
        panel.edit_name.setText("测试步骤")
        panel.edit_script.setText(str(Path("Z:/missing/script.py")))
        panel.edit_args.clear()

        monkeypatch.setattr("os.path.exists", lambda _path: False)
        monkeypatch.setattr(step_editor_module, "msg_question", lambda *_args, **_kwargs: QMessageBox.No)
        monkeypatch.setattr(step_editor_module, "update_step", lambda *args, **kwargs: update_calls.append((args, kwargs)))

        assert panel.save_step() is False
        assert update_calls == []
    finally:
        panel.deleteLater()
        assert app is not None
