# -*- coding: utf-8 -*-
"""MainWindow 动作 helper 测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QMessageBox, QWidget
from PySide6.QtCore import Qt

import ui.main_window as main_window_module
from ui.json_actions import EXPORT_SUCCESS_NOTE, export_json_action, import_json_action
from ui.main_window import MainWindow
from ui.run_actions import run_engine_mode
from ui.step_editor import StepEditorPanel
from ui.step_table import StepTablePanel


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


class DummyLabel:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


class DummyStepEditor:
    def __init__(self, step_id=0, *, dirty=False, save_result=True):
        self._step_id = step_id
        self._dirty = dirty
        self.save_result = save_result
        self.cleared = False
        self.loaded_step_id = None
        self.reset_calls = 0
        self.discard_calls = 0
        self.save_calls = 0

    def clear(self):
        self.cleared = True

    def load_step(self, step_id):
        self.loaded_step_id = step_id

    def is_dirty(self):
        return self._dirty

    def save_step(self):
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


class DummyRunControl:
    def __init__(self):
        self.calls = []

    def set_selected_step(self, step_id, stage_uid):
        self.calls.append((step_id, stage_uid))


class DummyLogPanel:
    def __init__(self):
        self.calls = []

    def set_context(self, **kwargs):
        self.calls.append(kwargs)


class DummyBoard:
    def __init__(self, *, fail_stage=False):
        self.calls = []
        self.fail_stage = fail_stage
        self.loaded_workflow_id = None

    def select_stage(self, stage_uid, emit_signal=True):
        if self.fail_stage:
            raise RuntimeError("board sync failed")
        self.calls.append(("stage", stage_uid, emit_signal))

    def select_step(self, step_id, emit_signal=True):
        self.calls.append(("step", step_id, emit_signal))

    def load_workflow(self, workflow_id):
        self.loaded_workflow_id = workflow_id

    def selected_stage_uid(self):
        return "stage-b"


class DummyStepTable:
    def __init__(self, *, fail_stage=False):
        self.calls = []
        self.fail_stage = fail_stage
        self._row_by_step_id = {}
        self._stage_by_step_id = {}
        self._selected_step_id = None
        self._selected_stage_uid = None
        self.table = None
        self.loaded_workflow_id = None

    def set_selected_stage_context(self, stage_uid, *, clear_step_selection=False):
        if self.fail_stage:
            raise RuntimeError("table sync failed")
        self.calls.append(("stage", stage_uid, clear_step_selection))
        self._selected_stage_uid = stage_uid
        if clear_step_selection:
            self._selected_step_id = None

    def select_step(self, step_id, emit_signal=True):
        self.calls.append(("step", step_id, emit_signal))
        self._selected_step_id = int(step_id)
        self._selected_stage_uid = self.get_stage_uid_for_step(step_id)

    def get_stage_uid_for_step(self, step_id):
        return self._stage_by_step_id.get(int(step_id), "stage-b")

    def load_steps(self, workflow_id):
        self.loaded_workflow_id = workflow_id

    def apply_orders_and_stage_updates(self, stage_overrides, step_ids_in_order):
        self.calls.append(("apply", stage_overrides, step_ids_in_order))
        return True

    def get_selection_snapshot(self):
        return {
            "step_id": self._selected_step_id,
            "stage_uid": self._selected_stage_uid,
        }

    def has_step(self, step_id):
        return int(step_id) in self._row_by_step_id


class DummySignalsTable:
    def __init__(self, row_count=6):
        self._blocked = False
        self.row_count = row_count
        self.current_cell = None

    def signalsBlocked(self):
        return self._blocked

    def blockSignals(self, value):
        self._blocked = bool(value)

    def rowCount(self):
        return self.row_count

    def setCurrentCell(self, row, column):
        self.current_cell = (row, column)


def test_create_plan_switch_registers_dag_button():
    app = QApplication.instance() or QApplication([])
    holder = SimpleNamespace()

    switch = MainWindow._create_plan_switch(holder)

    assert switch is not None
    assert [(btn.text(), index) for btn, index in holder._view_buttons] == [
        ("阶段", 0),
        ("批次", 1),
        ("列表", 2),
    ]
    assert app is not None


def test_step_table_stage_context_clears_selection_and_current_cell():
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    panel.table.setRowCount(1)
    panel.table.setColumnCount(1)
    item = QTableWidgetItem("步骤")
    item.setData(Qt.UserRole, 42)
    panel.table.setItem(0, 0, item)
    panel.table.setCurrentCell(0, 0)
    panel._selected_step_id = 42

    panel.set_selected_stage_context("stage-b", clear_step_selection=True)

    assert app is not None
    assert panel._selected_step_id is None
    assert panel.table.selectedItems() == []
    assert panel.table.currentRow() == -1
    assert panel.table.currentColumn() == -1


def test_restore_step_selection_silently_syncs_board_selection():
    table_widget = DummySignalsTable()
    board = DummyBoard()
    step_table = DummyStepTable()
    step_table.table = table_widget
    step_table._row_by_step_id = {42: 3}
    step_table._stage_by_step_id = {42: "stage-a"}
    window = SimpleNamespace(
        step_editor=DummyStepEditor(step_id=42),
        step_table=step_table,
        workbench_board=board,
    )

    MainWindow._restore_step_selection_silently(window)

    assert step_table.calls == [("step", 42, False)]
    assert step_table._selected_step_id == 42
    assert step_table._selected_stage_uid == "stage-a"
    assert table_widget.current_cell is None
    assert board.calls == [("step", 42, False)]


def test_on_stage_selected_aborts_when_unsaved_confirmation_rejects():
    board = DummyBoard()
    step_table = DummyStepTable()
    step_table._stage_by_step_id = {21: "stage-a"}
    window = SimpleNamespace(
        _current_workflow_id=9,
        workbench_board=board,
        step_table=step_table,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        step_editor=DummyStepEditor(step_id=21),
        run_control=DummyRunControl(),
        log_panel=DummyLogPanel(),
    )

    def reject_with_restore(**kwargs):
        MainWindow._restore_step_selection_silently(window)
        return False

    window._confirm_discard_unsaved = reject_with_restore

    MainWindow._on_stage_selected(window, "stage-b")

    assert board.calls == [("step", 21, False)]
    assert step_table.calls == [("step", 21, False)]
    assert step_table._selected_step_id == 21
    assert step_table._selected_stage_uid == "stage-a"
    assert window.step_editor.cleared is False
    assert window.run_control.calls == []
    assert window.log_panel.calls == []


def test_on_stage_selected_syncs_board_and_step_table_context(monkeypatch):
    board = DummyBoard()
    step_table = DummyStepTable()
    window = SimpleNamespace(
        _confirm_discard_unsaved=lambda **kwargs: True,
        _current_workflow_id=9,
        workbench_board=board,
        step_table=step_table,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        step_editor=DummyStepEditor(step_id=21),
        run_control=DummyRunControl(),
        log_panel=DummyLogPanel(),
    )
    monkeypatch.setattr(
        main_window_module,
        "list_stages",
        lambda workflow_id: [
            SimpleNamespace(uid="stage-a", name="准备"),
            SimpleNamespace(uid="stage-b", name="处理"),
        ],
    )

    MainWindow._on_stage_selected(window, "stage-b")

    assert board.calls == [("stage", "stage-b", False)]
    assert step_table.calls == [("stage", "stage-b", True)]
    assert window.lbl_inspector_kind.text == "选中阶段"
    assert window.lbl_inspector_title.text == "S2 处理"
    assert window.step_editor.cleared is True
    assert window.run_control.calls == [(None, "stage-b")]
    assert window.log_panel.calls == [{"workflow_id": 9, "step_id": None}]


def test_on_stage_selected_aborts_ui_updates_when_board_sync_fails(monkeypatch):
    board = DummyBoard(fail_stage=True)
    step_table = DummyStepTable()
    window = SimpleNamespace(
        _confirm_discard_unsaved=lambda **kwargs: True,
        _current_workflow_id=9,
        workbench_board=board,
        step_table=step_table,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        step_editor=DummyStepEditor(step_id=21),
        run_control=DummyRunControl(),
        log_panel=DummyLogPanel(),
    )
    monkeypatch.setattr(main_window_module, "list_stages", lambda workflow_id: [])

    MainWindow._on_stage_selected(window, "stage-b")

    assert board.calls == []
    assert step_table.calls == []
    assert window.lbl_inspector_kind.text is None
    assert window.lbl_inspector_title.text is None
    assert window.step_editor.cleared is False
    assert window.run_control.calls == []
    assert window.log_panel.calls == []


def test_on_stage_selected_aborts_ui_updates_when_step_table_sync_fails(monkeypatch):
    board = DummyBoard()
    step_table = DummyStepTable(fail_stage=True)
    window = SimpleNamespace(
        _confirm_discard_unsaved=lambda **kwargs: True,
        _current_workflow_id=9,
        workbench_board=board,
        step_table=step_table,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        step_editor=DummyStepEditor(step_id=21),
        run_control=DummyRunControl(),
        log_panel=DummyLogPanel(),
    )
    monkeypatch.setattr(main_window_module, "list_stages", lambda workflow_id: [])

    MainWindow._on_stage_selected(window, "stage-b")

    assert board.calls == [("stage", "stage-b", False)]
    assert step_table.calls == []
    assert window.lbl_inspector_kind.text is None
    assert window.lbl_inspector_title.text is None
    assert window.step_editor.cleared is False
    assert window.run_control.calls == []
    assert window.log_panel.calls == []


def test_on_step_selected_syncs_step_table_before_loading_editor(monkeypatch):
    board = DummyBoard()
    step_table = DummyStepTable()
    step_editor = DummyStepEditor(step_id=7)
    run_control = DummyRunControl()
    log_panel = DummyLogPanel()
    window = SimpleNamespace(
        _confirm_discard_unsaved=lambda **kwargs: True,
        step_table=step_table,
        step_editor=step_editor,
        workbench_board=board,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        run_control=run_control,
        log_panel=log_panel,
        _current_workflow_id=11,
    )
    monkeypatch.setattr(main_window_module, "get_step_by_id", lambda step_id: SimpleNamespace(name="汇总"))
    MainWindow._on_step_selected(window, 33)

    assert step_table.calls[0] == ("step", 33, False)
    assert board.calls == [("step", 33, False)]
    assert step_editor.loaded_step_id == 33
    assert run_control.calls == [(33, "stage-b")]
    assert log_panel.calls == [{"workflow_id": 11, "step_id": 33}]


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


def test_on_step_selected_ignores_reselecting_current_step():
    confirm_calls = []
    window = SimpleNamespace(
        step_editor=SimpleNamespace(_step_id=33),
        _confirm_discard_unsaved=lambda **kwargs: confirm_calls.append(kwargs) or True,
    )

    MainWindow._on_step_selected(window, 33)

    assert confirm_calls == []


def test_on_stage_selected_ignores_reselecting_current_stage():
    confirm_calls = []
    window = SimpleNamespace(
        step_editor=SimpleNamespace(_step_id=None),
        workbench_board=SimpleNamespace(selected_stage_uid=lambda: "stage-a"),
        step_table=SimpleNamespace(get_selection_snapshot=lambda: {"step_id": None, "stage_uid": "stage-a"}),
        _confirm_discard_unsaved=lambda **kwargs: confirm_calls.append(kwargs) or True,
    )

    MainWindow._on_stage_selected(window, "stage-a")

    assert confirm_calls == []


def test_restore_workflow_selection_keeps_context_when_filtered_out():
    class DummyListWidget:
        def __init__(self):
            self.rows = []
            self.cleared = False
            self._blocked = False

        def signalsBlocked(self):
            return self._blocked

        def blockSignals(self, value):
            self._blocked = bool(value)

        def count(self):
            return 0

        def item(self, _index):
            return None

        def setCurrentRow(self, row):
            self.rows.append(row)

    list_widget = DummyListWidget()
    window = SimpleNamespace(
        _current_workflow_id=42,
        workflow_list=SimpleNamespace(list_widget=list_widget),
    )

    MainWindow._restore_workflow_selection_silently(window)

    assert list_widget.rows == [-1]
    assert window._current_workflow_id == 42


def test_restore_step_selection_reports_failure_when_step_table_restore_fails():
    window = SimpleNamespace(
        step_editor=SimpleNamespace(_step_id=42),
        step_table=SimpleNamespace(
            select_step=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("table boom")),
        ),
        workbench_board=SimpleNamespace(select_step=lambda *_args, **_kwargs: None),
    )

    assert MainWindow._restore_step_selection_silently(window) is False


def test_restore_step_selection_reports_failure_when_board_restore_fails():
    window = SimpleNamespace(
        step_editor=SimpleNamespace(_step_id=42),
        step_table=SimpleNamespace(
            select_step=lambda *_args, **_kwargs: None,
            get_selection_snapshot=lambda: {"step_id": 42, "stage_uid": "stage-a"},
        ),
        workbench_board=SimpleNamespace(
            select_step=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("board boom")),
        ),
    )

    assert MainWindow._restore_step_selection_silently(window) is False


def test_step_table_single_selection_emits_step_selected_only_once():
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    emitted = []
    panel.step_selected.connect(emitted.append)
    panel.table.setRowCount(1)
    panel.table.setColumnCount(1)
    item = QTableWidgetItem("步骤")
    item.setData(Qt.UserRole, 42)
    panel.table.setItem(0, 0, item)
    panel._row_meta = [{"kind": "step", "stage_uid": "stage-a"}]
    panel.table.setCurrentCell(0, 0)

    panel._on_selection_changed(0, 0, -1, -1)
    panel._on_selection_changed_by_selection()

    assert emitted == [42]
    assert app is not None


def test_step_table_stage_context_clear_allows_reselecting_same_step():
    app = QApplication.instance() or QApplication([])
    panel = StepTablePanel()
    emitted = []
    panel.step_selected.connect(emitted.append)
    panel.table.setRowCount(1)
    panel.table.setColumnCount(1)
    item = QTableWidgetItem("步骤")
    item.setData(Qt.UserRole, 42)
    panel.table.setItem(0, 0, item)
    panel._row_meta = [{"kind": "step", "stage_uid": "stage-a"}]
    panel._row_by_step_id = {42: 0}

    panel.table.setCurrentCell(0, 0)
    panel._on_selection_changed(0, 0, -1, -1)
    panel.set_selected_stage_context("stage-a", clear_step_selection=True)
    panel.table.setCurrentCell(0, 0)
    panel._on_selection_changed(0, 0, -1, -1)

    assert emitted == [42, 42]
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


def test_on_steps_changed_restores_selected_step_context(monkeypatch):
    board = DummyBoard()
    step_table = DummyStepTable()
    step_table._row_by_step_id = {42: 3}
    step_table._stage_by_step_id = {42: "stage-a"}
    step_editor = DummyStepEditor(step_id=42)
    run_control = DummyRunControl()
    log_panel = DummyLogPanel()
    dag_calls = []
    window = SimpleNamespace(
        _current_workflow_id=11,
        step_editor=step_editor,
        step_table=step_table,
        workbench_board=board,
        run_control=run_control,
        log_panel=log_panel,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        _refresh_workbench_header=lambda workflow_id: dag_calls.append(("header", workflow_id)),
        _async_load_dag=lambda workflow_id: dag_calls.append(("dag", workflow_id)),
    )
    window._reload_steps_views = MainWindow._reload_steps_views.__get__(window, SimpleNamespace)
    monkeypatch.setattr(main_window_module.QTimer, "singleShot", lambda _ms, callback: callback())
    monkeypatch.setattr(main_window_module, "get_step_by_id", lambda step_id: SimpleNamespace(name="汇总步骤"))

    MainWindow._on_steps_changed(window)

    assert step_table.loaded_workflow_id == 11
    assert board.loaded_workflow_id == 11
    assert step_table.calls == [("step", 42, False)]
    assert board.calls == [("step", 42, False)]
    assert step_editor.loaded_step_id == 42
    assert run_control.calls == [(42, "stage-a")]
    assert log_panel.calls == [{"workflow_id": 11, "step_id": 42}]
    assert window.lbl_inspector_kind.text == "选中步骤"
    assert window.lbl_inspector_title.text == "汇总步骤"
    assert dag_calls == [("header", 11), ("dag", 11)]


def test_reload_steps_views_clears_missing_restore_target(monkeypatch):
    board = DummyBoard()
    step_table = DummyStepTable()
    step_table._row_by_step_id = {}
    step_editor = DummyStepEditor(step_id=42)
    run_control = DummyRunControl()
    log_panel = DummyLogPanel()
    dag_calls = []
    window = SimpleNamespace(
        step_table=step_table,
        workbench_board=board,
        step_editor=step_editor,
        run_control=run_control,
        log_panel=log_panel,
        lbl_inspector_kind=DummyLabel(),
        lbl_inspector_title=DummyLabel(),
        _refresh_workbench_header=lambda workflow_id: dag_calls.append(("header", workflow_id)),
        _async_load_dag=lambda workflow_id: dag_calls.append(("dag", workflow_id)),
    )
    monkeypatch.setattr(main_window_module.QTimer, "singleShot", lambda _ms, callback: callback())

    MainWindow._reload_steps_views(window, 11, restore_step_id=42, restore_stage_uid=None, reload_editor=True)

    assert step_table.loaded_workflow_id == 11
    assert board.loaded_workflow_id == 11
    assert step_editor.cleared is True
    assert window.lbl_inspector_kind.text == "Inspector"
    assert window.lbl_inspector_title.text == "选择步骤或阶段"
    assert run_control.calls == [(None, None)]
    assert log_panel.calls == [{"workflow_id": 11, "step_id": None}]
    assert dag_calls == [("header", 11), ("dag", 11)]

def test_async_workflow_refresh_callbacks_ignore_stale_workflow_id():
    window = MainWindow.__new__(MainWindow)
    window._current_workflow_id = 2

    dag_calls = []
    history_calls = []
    window.dag_view = SimpleNamespace(update_dag=lambda workflow_id: dag_calls.append(workflow_id))
    window.run_history = SimpleNamespace(load_history=lambda workflow_id: history_calls.append(workflow_id))

    window._async_load_dag(1)
    window._async_load_history(1)

    assert dag_calls == []
    assert history_calls == []

    window._async_load_dag(2)
    window._async_load_history(2)

    assert dag_calls == [2]
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

    class DummyMessageBox:
        Warning = QMessageBox.Warning
        AcceptRole = QMessageBox.AcceptRole
        Ok = QMessageBox.Ok

        def __init__(self, parent):
            self._clicked = None

        def setWindowTitle(self, title):
            pass

        def setText(self, text):
            pass

        def setIcon(self, icon):
            pass

        def addButton(self, *args):
            button = object()
            if args and args[0] == "定位问题步骤":
                self._clicked = button
            return button

        def setStyleSheet(self, style):
            pass

        def exec(self):
            pass

        def clickedButton(self):
            return self._clicked

    from exceptions import DependencyError

    monkeypatch.setattr(panel, "_find_step_id_referenced_by_dependency_error", lambda error: 42)
    monkeypatch.setattr(panel, "select_step", lambda step_id: (_ for _ in ()).throw(RuntimeError("row missing")))
    monkeypatch.setattr(panel, "_notify_status", statuses.append)
    monkeypatch.setattr("ui.step_table.panel.QMessageBox", DummyMessageBox)

    panel._show_dependency_mutation_error("操作无效", DependencyError("bad dependency"), "请先调整依赖")

    assert statuses == ["未能定位触发依赖校验的步骤：row missing"]
    assert app is not None
