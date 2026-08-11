# -*- coding: utf-8 -*-
"""批量删除 / 批量改阶段（StepTablePanel._batch_delete_steps / _batch_change_stage）测试。

桩函数签名与 ui.theme.msg_* 保持一致（parent, dark, title, text, ...）；
若被调代码缺传 self._dark，桩函数自身抛 TypeError，测试直接失败。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
import stage_mutation_service
import ui.theme
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.step_table import StepTablePanel

# 行模型：0 为阶段标题条（应被过滤），1/2 为步骤行
ROW_META = [
    {"kind": "stage_header", "stage_uid": "s1", "step_id": None},
    {"kind": "step", "step_id": 11, "stage_uid": "s1"},
    {"kind": "step", "step_id": 12, "stage_uid": "s2"},
]


def _make_panel() -> StepTablePanel:
    QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    panel._dark = False
    panel._workflow_id = 7
    panel._edit_enabled = True
    panel._row_meta = list(ROW_META)
    return panel


def _install_msg_stubs(monkeypatch, question_answer=QMessageBox.Yes):
    """安装与 ui.theme.msg_* 同签名的桩；返回调用记录列表。

    签名严格一致：缺参（如未传 dark）时桩函数自身抛 TypeError。
    """
    calls = []

    def msg_information(parent, dark, title, text):
        calls.append(("information", (parent, dark, title, text)))

    def msg_critical(parent, dark, title, text):
        calls.append(("critical", (parent, dark, title, text)))

    def msg_question(parent, dark, title, text, buttons=None, default_button=None):
        calls.append(("question", (parent, dark, title, text)))
        return question_answer

    monkeypatch.setattr(ui.theme, "msg_information", msg_information)
    monkeypatch.setattr(ui.theme, "msg_critical", msg_critical)
    monkeypatch.setattr(ui.theme, "msg_question", msg_question)
    return calls


# ---------------------------------------------------------------------------
# _batch_delete_steps
# ---------------------------------------------------------------------------

def test_batch_delete_steps_no_rows_returns_without_messages(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch)
        deleted = []
        monkeypatch.setattr(database, "delete_step", lambda sid: deleted.append(sid))

        panel._batch_delete_steps([])

        assert calls == []
        assert deleted == []
    finally:
        panel.close()


def test_batch_delete_steps_not_edit_enabled_shows_info(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch)
        deleted = []
        monkeypatch.setattr(database, "delete_step", lambda sid: deleted.append(sid))
        panel._edit_enabled = False
        panel._dark = True

        panel._batch_delete_steps([1, 2])

        assert calls == [
            ("information", (panel, True, "提示", '请先开启"编辑"。')),
        ]
        assert deleted == []
    finally:
        panel.close()


def test_batch_delete_steps_confirm_deletes_and_reloads(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch, question_answer=QMessageBox.Yes)
        deleted = []
        loaded = []
        monkeypatch.setattr(database, "delete_step", lambda sid: deleted.append(sid))
        monkeypatch.setattr(panel, "load_steps", lambda workflow_id: loaded.append(workflow_id))

        # 含阶段标题条行(0)与越界行(99)，均应被过滤
        panel._batch_delete_steps([0, 1, 2, 99])

        assert deleted == [11, 12]
        assert loaded == [7]
        assert calls == [
            (
                "question",
                (
                    panel,
                    False,
                    "批量删除确认",
                    "确定删除选中的 2 个步骤吗？此操作不可撤销。",
                ),
            ),
        ]
    finally:
        panel.close()


def test_batch_delete_steps_cancel_skips_delete(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch, question_answer=QMessageBox.No)
        deleted = []
        loaded = []
        monkeypatch.setattr(database, "delete_step", lambda sid: deleted.append(sid))
        monkeypatch.setattr(panel, "load_steps", lambda workflow_id: loaded.append(workflow_id))

        panel._batch_delete_steps([1, 2])

        assert deleted == []
        assert loaded == []
        assert len(calls) == 1 and calls[0][0] == "question"
    finally:
        panel.close()


def test_batch_delete_steps_db_error_shows_critical(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch, question_answer=QMessageBox.Yes)
        loaded = []

        def boom(sid):
            raise RuntimeError("db boom")

        monkeypatch.setattr(database, "delete_step", boom)
        monkeypatch.setattr(panel, "load_steps", lambda workflow_id: loaded.append(workflow_id))

        panel._batch_delete_steps([1, 2])

        assert loaded == []
        assert calls == [
            (
                "question",
                (
                    panel,
                    False,
                    "批量删除确认",
                    "确定删除选中的 2 个步骤吗？此操作不可撤销。",
                ),
            ),
            ("critical", (panel, False, "批量删除失败", "db boom")),
        ]
    finally:
        panel.close()


# ---------------------------------------------------------------------------
# _batch_change_stage
# ---------------------------------------------------------------------------

def test_batch_change_stage_no_rows_or_target_returns(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch)
        moved = []
        monkeypatch.setattr(
            stage_mutation_service, "move_step_to_stage",
            lambda workflow_id, sid, stage_uid: moved.append((workflow_id, sid, stage_uid)),
        )

        panel._batch_change_stage([], "t1")
        panel._batch_change_stage([1, 2], "")
        panel._batch_change_stage(None, "t1")

        assert calls == []
        assert moved == []
    finally:
        panel.close()


def test_batch_change_stage_not_edit_enabled_shows_info(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch)
        moved = []
        monkeypatch.setattr(
            stage_mutation_service, "move_step_to_stage",
            lambda workflow_id, sid, stage_uid: moved.append((workflow_id, sid, stage_uid)),
        )
        panel._edit_enabled = False
        panel._dark = True

        panel._batch_change_stage([1, 2], "t1")

        assert calls == [
            ("information", (panel, True, "提示", '请先开启"编辑"。')),
        ]
        assert moved == []
    finally:
        panel.close()


def test_batch_change_stage_success_moves_all_and_reloads(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch)
        moved = []
        loaded = []
        monkeypatch.setattr(
            stage_mutation_service, "move_step_to_stage",
            lambda workflow_id, sid, stage_uid: moved.append((workflow_id, sid, stage_uid)),
        )
        monkeypatch.setattr(panel, "load_steps", lambda workflow_id: loaded.append(workflow_id))

        panel._batch_change_stage([0, 1, 2, 99], "t1")

        assert moved == [(7, 11, "t1"), (7, 12, "t1")]
        assert loaded == [7]
        assert calls == []
    finally:
        panel.close()


def test_batch_change_stage_db_error_shows_critical(monkeypatch):
    panel = _make_panel()
    try:
        calls = _install_msg_stubs(monkeypatch)
        loaded = []

        def boom(workflow_id, sid, stage_uid):
            raise RuntimeError("move boom")

        monkeypatch.setattr(stage_mutation_service, "move_step_to_stage", boom)
        monkeypatch.setattr(panel, "load_steps", lambda workflow_id: loaded.append(workflow_id))

        panel._batch_change_stage([1, 2], "t1")

        assert loaded == []
        assert calls == [
            ("critical", (panel, False, "批量改阶段失败", "move boom")),
        ]
    finally:
        panel.close()
