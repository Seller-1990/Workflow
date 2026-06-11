# -*- coding: utf-8 -*-
"""MainWindow 选择同步与步骤视图恢复测试。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication, QTableWidgetItem
from PySide6.QtCore import Qt

import ui.main_window as main_window_module
from ui.main_window import MainWindow
from ui.step_table import StepTablePanel

from _main_window_test_utils import DummyStepEditor


class DummyLabel:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


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
