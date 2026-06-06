# -*- coding: utf-8 -*-
"""MainWindow 动作 helper 测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ui.json_actions import EXPORT_SUCCESS_NOTE, export_json_action, import_json_action
from ui.run_actions import run_engine_mode


class DummyEngine:
    def __init__(self):
        self.calls = []

    def run_all(self, workflow_id):
        self.calls.append(("run_all", workflow_id))
        return True

    def run_from(self, workflow_id, step_id):
        self.calls.append(("run_from", workflow_id, step_id))
        return True

    def run_only(self, workflow_id, step_id):
        self.calls.append(("run_only", workflow_id, step_id))
        return True

    def run_stage(self, workflow_id, stage_uid):
        self.calls.append(("run_stage", workflow_id, stage_uid))
        return True

    def run_from_stage(self, workflow_id, stage_uid):
        self.calls.append(("run_from_stage", workflow_id, stage_uid))
        return True

    def retry_failed(self, workflow_id):
        self.calls.append(("retry_failed", workflow_id))
        return True


def test_import_json_action_imports_notifies_and_reloads(tmp_path):
    json_path = tmp_path / "workflow.json"
    json_path.write_text("{}", encoding="utf-8")
    imported_paths = []
    messages = []
    reloaded = []

    ok = import_json_action(
        parent=None,
        dark_mode=False,
        reload_workflows=lambda: reloaded.append(True),
        selected_path=str(json_path),
        importer=lambda path: imported_paths.append(path) or 3,
        show_information=lambda *args: messages.append(args),
        show_critical=lambda *args: messages.append(("critical", args)),
    )

    assert ok is True
    assert imported_paths == [json_path]
    assert reloaded == [True]
    assert messages[0][2] == "导入成功"
    assert "3 个工作流" in messages[0][3]


def test_import_json_action_reports_failure_without_reload(tmp_path):
    json_path = tmp_path / "broken.json"
    reloaded = []
    critical_messages = []

    ok = import_json_action(
        parent=None,
        dark_mode=False,
        reload_workflows=lambda: reloaded.append(True),
        selected_path=str(json_path),
        importer=lambda path: (_ for _ in ()).throw(ValueError("bad json")),
        show_information=lambda *args: None,
        show_critical=lambda *args: critical_messages.append(args),
    )

    assert ok is False
    assert reloaded == []
    assert critical_messages[0][2] == "导入失败"
    assert critical_messages[0][3] == "bad json"


def test_export_json_action_exports_with_secret_masking_note(tmp_path):
    json_path = tmp_path / "export.json"
    exported_paths = []
    messages = []

    ok = export_json_action(
        parent=None,
        dark_mode=False,
        selected_path=str(json_path),
        exporter=lambda path: exported_paths.append(path),
        show_information=lambda *args: messages.append(args),
        show_critical=lambda *args: messages.append(("critical", args)),
    )

    assert ok is True
    assert exported_paths == [json_path]
    assert messages[0][2] == "导出成功"
    assert EXPORT_SUCCESS_NOTE in messages[0][3]


def test_run_engine_mode_dispatches_supported_modes():
    cases = [
        ("full", None, ("run_all", 7)),
        ("from_step", 11, ("run_from", 7, 11)),
        ("only_step", 12, ("run_only", 7, 12)),
        ("only_stage", "s1", ("run_stage", 7, "s1")),
        ("from_stage", "s2", ("run_from_stage", 7, "s2")),
        ("retry_failed", None, ("retry_failed", 7)),
    ]

    for mode, param, expected in cases:
        engine = DummyEngine()
        assert run_engine_mode(engine, workflow_id=7, mode=mode, param=param) is True
        assert engine.calls == [expected]


def test_run_engine_mode_unknown_mode_returns_false_without_calling_engine():
    engine = DummyEngine()

    assert run_engine_mode(engine, workflow_id=7, mode="unknown") is False
    assert engine.calls == []
