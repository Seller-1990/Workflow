# -*- coding: utf-8 -*-
"""MainWindow 动作 helper 测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QLayout, QMainWindow, QMessageBox, QWidget

import ui.main_window as main_window_module
from ui import main_window_setup
from ui.json_actions import EXPORT_SUCCESS_NOTE, export_json_action, import_json_action
from ui.main_window import MainWindow
from ui.run_actions import run_engine_mode
from ui.step_editor import StepEditorPanel
from ui.step_table import StepTablePanel

from _main_window_test_utils import DummyStepEditor


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


def test_run_engine_mode_forwards_explicit_empty_step_override():
    calls = []

    class OverrideEngine:
        def run_only(self, workflow_id, step_id, run_arg_overrides=None):
            calls.append((workflow_id, step_id, run_arg_overrides))
            return True

    overrides = {"step-1": []}

    assert run_engine_mode(
        OverrideEngine(),
        workflow_id=7,
        mode="only_step",
        param=12,
        run_arg_overrides=overrides,
    ) is True
    assert calls == [(7, 12, {"step-1": []})]


class DummyWorkflowConfig:
    def __init__(self, *, dirty=False, save_result=True):
        self._dirty = dirty
        self.save_result = save_result
        self.save_calls = 0
        self.reset_calls = 0
        self.discard_calls = 0
        self.refresh_calls = 0

    def is_dirty(self):
        return self._dirty

    def save_config(self):
        self.save_calls += 1
        if self.save_result:
            self._dirty = False
        return self.save_result

    def reset_dirty_state(self):
        self.reset_calls += 1
        self._dirty = False

    def discard_changes(self):
        self.discard_calls += 1
        self._dirty = False

    def refresh_webhooks(self):
        self.refresh_calls += 1


def test_create_plan_switch_registers_stage_and_list_buttons():
    app = QApplication.instance() or QApplication([])
    holder = SimpleNamespace()

    switch = MainWindow._create_plan_switch(holder)

    assert switch is not None
    assert [(btn.text(), index) for btn, index in holder._view_buttons] == [
        ("阶段", 0),
        ("列表", 1),
    ]
    assert app is not None


def test_panel_toggle_wrappers_forward_silent_mode(monkeypatch):
    window = SimpleNamespace()
    calls = []
    monkeypatch.setattr(
        main_window_module.panel_controller,
        "toggle_left_panel",
        lambda target, *, silent=False: calls.append(("left", target, silent)),
    )
    monkeypatch.setattr(
        main_window_module.panel_controller,
        "toggle_right_panel",
        lambda target, *, silent=False: calls.append(("right", target, silent)),
    )

    MainWindow._toggle_left_panel(window, silent=True)
    MainWindow._toggle_right_panel(window, silent=True)

    assert calls == [
        ("left", window, True),
        ("right", window, True),
    ]


def test_center_layout_keeps_default_size_constraint_for_scroll_pages():
    app = QApplication.instance() or QApplication([])

    class Shell(QMainWindow):
        _dark_mode = False

        def _set_edit_mode(self, *_args):
            pass

        def _action_save(self):
            pass

        def _on_header_run_clicked(self):
            pass

        def _toggle_left_panel(self):
            pass

        def _toggle_right_panel(self):
            pass

        def _update_border_widget_positions(self):
            pass

        def _refresh_border_fold_buttons(self):
            pass

        def _on_run_splitter_moved(self, *_args):
            pass

        def _apply_run_splitter_profile(self, *_args, **_kwargs):
            pass

        def _create_plan_switch(self):
            return main_window_setup.create_plan_switch(self)

    window = Shell()
    try:
        main_window_setup.setup_ui(window)

        assert window.center_container.layout().sizeConstraint() == QLayout.SetDefaultConstraint
    finally:
        window.close()
        window.deleteLater()
        assert app is not None


def test_switching_back_to_board_refreshes_board_layout():
    calls = []

    class DummyStack:
        def __init__(self):
            self.index = None

        def setCurrentIndex(self, index):
            self.index = index

    class DummyButton:
        def __init__(self):
            self.object_name = None

        def setObjectName(self, name):
            self.object_name = name

        def style(self):
            return self

        def unpolish(self, _widget):
            pass

        def polish(self, _widget):
            pass

    window = SimpleNamespace(
        plan_stack=DummyStack(),
        _view_buttons=[(DummyButton(), 0), (DummyButton(), 1)],
        workbench_board=SimpleNamespace(refresh_after_view_shown=lambda: calls.append("refresh")),
    )

    MainWindow._set_plan_view(window, 1)

    assert calls == []

    MainWindow._set_plan_view(window, 0)

    assert window.plan_stack.index == 0
    assert calls == ["refresh"]


def test_confirm_discard_unsaved_saves_dirty_workflow_config_before_switch(monkeypatch):
    app = QApplication.instance() or QApplication([])

    def fake_exec(self):
        self._clicked = next(btn for btn in self.buttons() if btn.text() == "保存并切换")

    def fake_clicked(self):
        return self._clicked

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)
    window = QWidget()
    window.workflow_config = DummyWorkflowConfig(dirty=True)
    window.step_editor = DummyStepEditor(step_id=7, dirty=False)
    window._restore_selection_silently = lambda reason: None
    window._should_check_workflow_config_dirty = MainWindow._should_check_workflow_config_dirty.__get__(window, SimpleNamespace)
    window._is_panel_dirty = MainWindow._is_panel_dirty.__get__(window, SimpleNamespace)
    window._build_dirty_message = MainWindow._build_dirty_message.__get__(window, SimpleNamespace)
    window._save_dirty_panels = MainWindow._save_dirty_panels.__get__(window, SimpleNamespace)
    window._discard_panel_changes = MainWindow._discard_panel_changes.__get__(window, SimpleNamespace)
    window._discard_dirty_panels = MainWindow._discard_dirty_panels.__get__(window, SimpleNamespace)
    window._reset_panel_dirty_state = MainWindow._reset_panel_dirty_state.__get__(window, SimpleNamespace)

    assert MainWindow._confirm_discard_unsaved(window, reason="switch_workflow", new_target=99) is True
    assert window.workflow_config.save_calls == 1
    assert window.step_editor.save_calls == 0
    window.deleteLater()
    assert app is not None


def test_confirm_discard_unsaved_uses_public_reset_api_on_discard(monkeypatch):
    app = QApplication.instance() or QApplication([])

    def fake_exec(self):
        self._clicked = next(btn for btn in self.buttons() if btn.text() == "不保存直接切换")

    def fake_clicked(self):
        return self._clicked

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)
    workflow_config = DummyWorkflowConfig(dirty=True)
    step_editor = DummyStepEditor(step_id=7, dirty=True)
    window = QWidget()
    window.workflow_config = workflow_config
    window.step_editor = step_editor
    window._restore_selection_silently = lambda reason: None
    window._should_check_workflow_config_dirty = MainWindow._should_check_workflow_config_dirty.__get__(window, SimpleNamespace)
    window._is_panel_dirty = MainWindow._is_panel_dirty.__get__(window, SimpleNamespace)
    window._build_dirty_message = MainWindow._build_dirty_message.__get__(window, SimpleNamespace)
    window._save_dirty_panels = MainWindow._save_dirty_panels.__get__(window, SimpleNamespace)
    window._discard_panel_changes = MainWindow._discard_panel_changes.__get__(window, SimpleNamespace)
    window._discard_dirty_panels = MainWindow._discard_dirty_panels.__get__(window, SimpleNamespace)
    window._reset_panel_dirty_state = MainWindow._reset_panel_dirty_state.__get__(window, SimpleNamespace)

    assert MainWindow._confirm_discard_unsaved(window, reason="switch_workflow", new_target=99) is True
    assert workflow_config.discard_calls == 1
    assert step_editor.discard_calls == 1
    assert workflow_config.reset_calls == 0
    assert step_editor.reset_calls == 0
    window.deleteLater()
    assert app is not None


def test_close_event_keeps_dirty_state_when_running_exit_is_cancelled(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class DummyEvent:
        def __init__(self):
            self.ignored = False
            self.accepted = False

        def ignore(self):
            self.ignored = True

        def accept(self):
            self.accepted = True

    engine = SimpleNamespace(
        is_running=True,
        cancel=lambda: (_ for _ in ()).throw(AssertionError("cancel should not run")),
        wait_for_completion=lambda timeout=10.0: True,
        shutdown=lambda wait=True: None,
        workflow_started=SimpleNamespace(disconnect=lambda *_args: None),
        workflow_finished=SimpleNamespace(disconnect=lambda *_args: None),
        step_started=SimpleNamespace(disconnect=lambda *_args: None),
        step_finished=SimpleNamespace(disconnect=lambda *_args: None),
        log_output=SimpleNamespace(disconnect=lambda *_args: None),
        progress_updated=SimpleNamespace(disconnect=lambda *_args: None),
        error_details=SimpleNamespace(disconnect=lambda *_args: None),
    )
    window = QWidget()
    window.engine = engine
    window._dark_mode = False
    window.workflow_config = DummyWorkflowConfig(dirty=True)
    window.step_editor = DummyStepEditor(step_id=7, dirty=True)
    window._restore_selection_silently = lambda reason: None
    window._should_check_workflow_config_dirty = MainWindow._should_check_workflow_config_dirty.__get__(window, SimpleNamespace)
    window._is_panel_dirty = MainWindow._is_panel_dirty.__get__(window, SimpleNamespace)
    window._build_dirty_message = MainWindow._build_dirty_message.__get__(window, SimpleNamespace)
    window._save_dirty_panels = MainWindow._save_dirty_panels.__get__(window, SimpleNamespace)
    window._discard_panel_changes = MainWindow._discard_panel_changes.__get__(window, SimpleNamespace)
    window._discard_dirty_panels = MainWindow._discard_dirty_panels.__get__(window, SimpleNamespace)
    window._reset_panel_dirty_state = MainWindow._reset_panel_dirty_state.__get__(window, SimpleNamespace)
    monkeypatch.setattr(main_window_module, "msg_question", lambda *args, **kwargs: QMessageBox.No)
    event = DummyEvent()

    MainWindow.closeEvent(window, event)

    assert event.ignored is True
    assert event.accepted is False
    assert window.workflow_config.is_dirty() is True
    assert window.step_editor.is_dirty() is True
    assert window.workflow_config.discard_calls == 0
    assert window.step_editor.discard_calls == 0
    window.deleteLater()
    assert app is not None


def test_step_editor_target_scope_filter_does_not_mark_dirty(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr("database.list_recent_workflows", lambda: [])
    panel = StepEditorPanel()
    try:
        panel._step_id = 1
        panel.reset_dirty_state()

        panel.combo_target_scope.setCurrentIndex(1)

        assert panel.is_dirty() is False

        panel.edit_name.setText("真正持久化字段")

        assert panel.is_dirty() is True
    finally:
        panel.deleteLater()
    assert app is not None


def test_open_webhook_manager_refreshes_workflow_config_dropdown_after_close(monkeypatch):
    calls = []

    class DummyDialog:
        def __init__(self, parent):
            self.parent = parent

        def exec_(self):
            calls.append(("exec", self.parent))

    monkeypatch.setattr(main_window_module, "WebhookManagerDialog", DummyDialog)
    window = SimpleNamespace(
        workflow_config=SimpleNamespace(refresh_webhooks=lambda: calls.append(("refresh", None))),
    )

    MainWindow._open_webhook_manager(window)

    assert calls == [("exec", window), ("refresh", None)]


def test_on_board_reorder_requested_uses_step_table_public_facade():
    calls = []
    board = SimpleNamespace(load_workflow=lambda workflow_id: calls.append(("board_reload", workflow_id)))
    statusbar = SimpleNamespace(showMessage=lambda message, timeout=0: calls.append(("status", message, timeout)))
    window = SimpleNamespace(
        _current_workflow_id=11,
        _require_edit_mode=lambda action_name: True,
        step_table=SimpleNamespace(
            apply_orders_and_stage_updates=lambda stage_overrides, step_ids_in_order: calls.append(
                ("apply", stage_overrides, step_ids_in_order)
            ) or True,
        ),
        workbench_board=board,
        _reload_workflow_surfaces=lambda **kwargs: calls.append(("reload", kwargs)),
        statusbar=statusbar,
    )

    MainWindow._on_board_reorder_requested(window, 5, "stage-b", [5, 7, 9])

    assert calls == [
        ("apply", {5: "stage-b"}, [5, 7, 9]),
        ("reload", {"select_step_id": 5}),
        ("status", "已更新步骤阶段和顺序", 5000),
    ]


def test_async_history_refresh_callback_ignores_stale_workflow_id():
    window = MainWindow.__new__(MainWindow)
    window._current_workflow_id = 2

    history_calls = []
    window.run_history = SimpleNamespace(
        load_history=lambda workflow_id: history_calls.append(workflow_id),
        # P1-C: 异步加载接口 —— 触发时应走 load_history_async
        load_history_async=lambda workflow_id: history_calls.append(workflow_id),
    )

    window._async_load_history(1)

    assert history_calls == []

    window._async_load_history(2)

    assert history_calls == [2]


def test_step_table_dependency_error_can_resolve_referenced_step(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    panel._workflow_id = 7

    monkeypatch.setattr(
        "ui.step_table.panel.get_steps_by_workflow",
        lambda workflow_id: [SimpleNamespace(id=41, uid="step-a"), SimpleNamespace(id=42, uid="step-b")],
    )

    from exceptions import DependencyError

    assert panel._find_step_id_referenced_by_dependency_error(
        DependencyError("跨阶段依赖不允许：步骤「B」依赖未来阶段的步骤 uid=step-b")
    ) == 42
    assert app is not None


def test_step_table_stage_mutation_dependency_error_uses_actionable_dialog(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    calls = []

    from exceptions import DependencyError

    monkeypatch.setattr(panel, "_show_dependency_mutation_error", lambda *args: calls.append(args))

    ok = panel._run_stage_mutation(
        lambda: (_ for _ in ()).throw(DependencyError("bad dependency")),
        "操作无效",
        "请先调整依赖",
        "未知错误",
    )

    assert ok is False
    assert calls and calls[0][0] == "操作无效"
    assert "bad dependency" in str(calls[0][1])
    assert app is not None


def test_step_table_dependency_error_resolves_quoted_and_json_uid(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    panel._workflow_id = 7

    monkeypatch.setattr(
        "ui.step_table.panel.get_steps_by_workflow",
        lambda workflow_id: [SimpleNamespace(id="41", uid="step-a"), SimpleNamespace(id=42, uid="step-b")],
    )

    from exceptions import DependencyError

    assert panel._find_step_id_referenced_by_dependency_error(
        DependencyError("跨阶段依赖不允许：uid='step-a' 指向未来阶段")
    ) == 41
    assert panel._find_step_id_referenced_by_dependency_error(
        DependencyError('{"error": "future dependency", "uid": "step-b"}')
    ) == 42
    assert app is not None


def test_step_table_dependency_error_locator_reports_select_failure(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    panel._workflow_id = 7
    statuses = []

    # V9.3：对话框创建移入 ui.theme.msg_custom_buttons——桩掉助手，返回 0 = 点击「定位问题步骤」
    monkeypatch.setattr("ui.theme.msg_custom_buttons", lambda *args, **kwargs: 0)

    from exceptions import DependencyError

    monkeypatch.setattr(panel, "_find_step_id_referenced_by_dependency_error", lambda error: 42)
    monkeypatch.setattr(panel, "select_step", lambda step_id: (_ for _ in ()).throw(RuntimeError("row missing")))
    monkeypatch.setattr(panel, "_notify_status", statuses.append)

    panel._show_dependency_mutation_error("操作无效", DependencyError("bad dependency"), "请先调整依赖")

    assert statuses == ["未能定位触发依赖校验的步骤：row missing"]
    assert app is not None


def test_close_event_logs_shutdown_failure(monkeypatch, caplog):
    class Event:
        accepted = False

        def accept(self):
            self.accepted = True

        def ignore(self):
            raise AssertionError("close should not be ignored")

    engine = SimpleNamespace(
        is_running=False,
        workflow_started=SimpleNamespace(disconnect=lambda *_args: None),
        workflow_finished=SimpleNamespace(disconnect=lambda *_args: None),
        step_started=SimpleNamespace(disconnect=lambda *_args: None),
        step_finished=SimpleNamespace(disconnect=lambda *_args: None),
        log_output=SimpleNamespace(disconnect=lambda *_args: None),
        progress_updated=SimpleNamespace(disconnect=lambda *_args: None),
        error_details=SimpleNamespace(disconnect=lambda *_args: None),
        shutdown=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("shutdown failed")),
    )
    window = SimpleNamespace(
        engine=engine,
        _confirm_discard_unsaved=lambda **_kwargs: True,
        log_panel=SimpleNamespace(append_log=lambda *_args: None),
        _on_workflow_started=lambda *_args: None,
        _on_workflow_finished=lambda *_args: None,
        _on_step_started=lambda *_args: None,
        _on_step_finished=lambda *_args: None,
        _on_progress_updated=lambda *_args: None,
        _on_error_details=lambda *_args: None,
    )
    event = Event()

    with caplog.at_level("ERROR", logger="ui.main_window"):
        MainWindow.closeEvent(window, event)

    assert event.accepted is True
    assert "关闭工作流引擎失败" in caplog.text
    assert "shutdown failed" in caplog.text
