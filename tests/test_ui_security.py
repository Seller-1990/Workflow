# -*- coding: utf-8 -*-
"""UI 安全与确认交互测试"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QMainWindow

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
        dialog.deleteLater()
        assert app is not None


def test_webhook_url_validation_requires_dingtalk_robot_endpoint(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])
    dialog = WebhookManagerDialog()
    try:
        assert dialog._validate_webhook_url(
            "https://oapi.dingtalk.com/robot/send?access_token=local-token"
        )
        assert not dialog._validate_webhook_url("https://example.com/robot/send?access_token=local-token")
        assert not dialog._validate_webhook_url("http://oapi.dingtalk.com/robot/send?access_token=local-token")
        assert not dialog._validate_webhook_url("https://oapi.dingtalk.com/robot/send")
        assert not dialog._validate_webhook_url("https://oapi.dingtalk.com/robot/send?access_token=")
    finally:
        dialog.deleteLater()
        assert app is not None


def test_webhook_test_blocks_non_edit_mode_and_invalid_url(monkeypatch):
    app = QApplication.instance() or QApplication([])
    sent = []
    info_messages = []
    warning_messages = []
    host = QMainWindow()
    host.is_edit_mode = lambda: False
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])
    monkeypatch.setattr(webhook_manager_module, "send_dingtalk_message", lambda *args: sent.append(args) or (True, "ok"))
    dialog = WebhookManagerDialog(host)
    try:
        monkeypatch.setattr(webhook_manager_module, "msg_information", lambda *args: info_messages.append(args))
        dialog.edit_url.setText("https://oapi.dingtalk.com/robot/send?access_token=local-token")

        dialog._on_test()

        assert sent == []
        assert info_messages[0][3] == "请先开启编辑模式"

        host.is_edit_mode = lambda: True
        monkeypatch.setattr(webhook_manager_module, "msg_warning", lambda *args: warning_messages.append(args))
        dialog.edit_url.setText("https://example.com/robot/send?access_token=local-token")

        dialog._on_test()

        assert sent == []
        assert warning_messages[-1][3] == "Webhook URL 格式无效，请使用钉钉机器人 HTTPS URL"
    finally:
        dialog.deleteLater()
        host.close()
        assert app is not None


def test_webhook_save_reselects_created_record_and_next_save_updates(monkeypatch):
    app = QApplication.instance() or QApplication([])
    created = []
    updated = []
    messages = []
    webhook = type(
        "Webhook",
        (),
        {
            "id": 10,
            "name": "财务通知",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=local-token",
            "keyword": "财务",
            "description": "desc",
        },
    )()
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [webhook])
    monkeypatch.setattr(webhook_manager_module, "create_webhook", lambda *args: created.append(args) or webhook)
    monkeypatch.setattr(webhook_manager_module, "update_webhook", lambda webhook_id, **kwargs: updated.append((webhook_id, kwargs)) or webhook)
    monkeypatch.setattr(database, "get_webhook_by_id", lambda webhook_id: webhook if webhook_id == 10 else None)
    monkeypatch.setattr(webhook_manager_module, "msg_information", lambda *args: messages.append(args))
    dialog = WebhookManagerDialog()
    try:
        dialog.edit_name.setText("财务通知")
        dialog.edit_url.setText("https://oapi.dingtalk.com/robot/send?access_token=local-token")
        dialog.edit_keyword.setText("财务")
        dialog.edit_desc.setPlainText("desc")
        assert dialog.is_dirty() is True

        dialog._on_save()

        assert created == [("财务通知", "https://oapi.dingtalk.com/robot/send?access_token=local-token", "财务", "desc")]
        assert dialog._current_webhook_id == 10
        assert dialog.is_dirty() is False

        dialog.edit_desc.setPlainText("desc-2")
        assert dialog.is_dirty() is True
        dialog._on_save()

        assert len(created) == 1
        assert updated == [
            (
                10,
                {
                    "name": "财务通知",
                    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=local-token",
                    "keyword": "财务",
                    "description": "desc-2",
                },
            )
        ]
        assert [msg[2] for msg in messages] == ["成功", "成功"]
    finally:
        dialog.deleteLater()
        assert app is not None


def test_webhook_manager_blocks_selection_switch_and_add_when_unsaved_confirmation_rejects(monkeypatch):
    app = QApplication.instance() or QApplication([])
    webhook1 = type(
        "Webhook",
        (),
        {
            "id": 1,
            "name": "机器人一",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token-1",
            "keyword": "k1",
            "description": "d1",
        },
    )()
    webhook2 = type(
        "Webhook",
        (),
        {
            "id": 2,
            "name": "机器人二",
            "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=token-2",
            "keyword": "k2",
            "description": "d2",
        },
    )()
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [webhook1, webhook2])
    monkeypatch.setattr(
        database,
        "get_webhook_by_id",
        lambda webhook_id: {1: webhook1, 2: webhook2}.get(webhook_id),
    )
    dialog = WebhookManagerDialog()
    try:
        dialog._load_webhooks(selected_id=1)
        dialog.edit_desc.setPlainText("changed")
        dialog._confirm_discard_unsaved = lambda **kwargs: False

        dialog._suppress_selection_change = True
        dialog.table.selectRow(1)
        dialog._suppress_selection_change = False
        dialog._on_selection_changed()

        assert dialog._current_webhook_id == 1
        assert dialog.table.currentRow() == 0
        assert dialog.edit_name.text() == "机器人一"

        dialog._on_add()

        assert dialog._current_webhook_id == 1
        assert dialog.edit_name.text() == "机器人一"
    finally:
        dialog.deleteLater()
        assert app is not None


def test_webhook_manager_close_event_blocks_when_unsaved_confirmation_rejects(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])
    dialog = WebhookManagerDialog()

    class DummyEvent:
        def __init__(self):
            self.ignored = False

        def ignore(self):
            self.ignored = True

    try:
        dialog.edit_name.setText("临时机器人")
        dialog._confirm_discard_unsaved = lambda **kwargs: False
        event = DummyEvent()

        dialog.closeEvent(event)

        assert event.ignored is True
    finally:
        dialog.deleteLater()
        assert app is not None


def test_webhook_save_and_delete_failures_are_logged_and_reported(monkeypatch):
    app = QApplication.instance() or QApplication([])
    logged = []
    critical_messages = []
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])
    monkeypatch.setattr(webhook_manager_module.logger, "exception", lambda *args, **kwargs: logged.append(args))
    monkeypatch.setattr(webhook_manager_module, "msg_critical", lambda *args: critical_messages.append(args))
    dialog = WebhookManagerDialog()
    try:
        dialog.edit_name.setText("财务通知")
        dialog.edit_url.setText("https://oapi.dingtalk.com/robot/send?access_token=local-token")
        monkeypatch.setattr(webhook_manager_module, "create_webhook", lambda *args: (_ for _ in ()).throw(RuntimeError("db locked")))

        dialog._on_save()

        assert logged[0][0] == "Webhook%s失败: %s"
        assert logged[0][1] == "保存"
        assert critical_messages[0][2] == "保存失败"
        assert critical_messages[0][3] == "db locked"

        dialog._current_webhook_id = 10
        dialog.edit_name.setText("财务通知")
        monkeypatch.setattr(webhook_manager_module, "msg_question", lambda *args, **kwargs: QMessageBox.Yes)
        monkeypatch.setattr(webhook_manager_module, "delete_webhook", lambda webhook_id: (_ for _ in ()).throw(RuntimeError("db busy")))

        dialog._on_delete()

        assert logged[1][1] == "删除"
        assert critical_messages[1][2] == "删除失败"
        assert critical_messages[1][3] == "db busy"
    finally:
        dialog.deleteLater()
        assert app is not None


def test_webhook_test_reuses_existing_result_timer(monkeypatch):
    app = QApplication.instance() or QApplication([])
    timers = []
    monkeypatch.setattr(webhook_manager_module, "list_webhooks", lambda: [])

    class FakeSignal:
        def __init__(self):
            self.callback = None

        def connect(self, callback):
            self.callback = callback

    class FakeTimer:
        def __init__(self, _parent=None):
            self.timeout = FakeSignal()
            self.started = []
            self.stop_calls = 0
            self.single_shot = None
            timers.append(self)

        def setSingleShot(self, value):
            self.single_shot = value

        def start(self, value):
            self.started.append(value)

        def stop(self):
            self.stop_calls += 1

    monkeypatch.setattr(webhook_manager_module, "QTimer", FakeTimer)
    monkeypatch.setattr(webhook_manager_module, "send_dingtalk_message", lambda *args: (True, "ok"))
    dialog = WebhookManagerDialog()
    try:
        dialog.edit_url.setText("https://oapi.dingtalk.com/robot/send?access_token=local-token")

        dialog._on_test()
        dialog._on_test()

        assert len(timers) == 1
        assert timers[0].single_shot is True
        assert timers[0].started == [5000, 5000]
        assert timers[0].stop_calls == 1
    finally:
        dialog.deleteLater()
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
