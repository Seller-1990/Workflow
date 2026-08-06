# -*- coding: utf-8 -*-
"""Run history pagination tests."""

import sys
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ui.run_history as run_history_module
from ui.run_history import RunHistoryPanel


class MockHistory:
    def __init__(self, id=1, run_id="run-1"):
        self.id = id
        self.run_id = run_id
        self.status = "success"
        self.reason = "manual"
        self.start_time = None
        self.duration_seconds = None
        self.log_dir = ""
        self.notify_status = None


def test_run_history_load_more_uses_offset_and_summarizes_new_page_only(monkeypatch):
    app = QApplication.instance() or QApplication([])
    panel = RunHistoryPanel()
    panel.PAGE_SIZE = 2
    calls = []
    pages = {
        0: [
            MockHistory(id=1, run_id="run-001"),
            MockHistory(id=2, run_id="run-002"),
            MockHistory(id=3, run_id="run-003"),
        ],
        2: [MockHistory(id=4, run_id="run-004")],
    }

    def fake_get_run_histories(workflow_id, limit=20, offset=0):
        calls.append((workflow_id, limit, offset))
        return pages.get(offset, [])

    monkeypatch.setattr(run_history_module, "get_run_histories_by_workflow", fake_get_run_histories)
    summary_calls = []
    monkeypatch.setattr(
        run_history_module,
        "get_step_log_summary_by_runs",
        lambda history_ids: summary_calls.append(list(history_ids)) or {},
    )

    panel.load_history(99)
    panel.load_more_history()

    assert calls == [(99, 3, 0), (99, 3, 2)]
    assert summary_calls == [[1, 2], [4]]
    assert [h.id for h in panel._all_histories] == [1, 2, 4]
    assert panel.btn_load_more.isHidden() is True
    assert app is not None


def test_load_history_async_marshals_back_to_gui_thread(monkeypatch):
    # P1-C: 后台线程查询结果必须经 Signal（AutoConnection→queued）回传 GUI 线程真正渲染。
    # 回归保护：若误用 QTimer.singleShot 从无事件循环的后台线程回程，信号永不到达，
    # 面板将永远空白（实测 PySide6 6.10.1）。
    app = QApplication.instance() or QApplication([])
    panel = RunHistoryPanel()
    panel.PAGE_SIZE = 100
    records = [MockHistory(id=1, run_id="run-001"), MockHistory(id=2, run_id="run-002")]

    monkeypatch.setattr(
        run_history_module, "get_run_histories_by_workflow", lambda *a, **k: records
    )
    monkeypatch.setattr(
        run_history_module,
        "get_step_log_summary_by_runs",
        lambda ids: {1: {"success": 1}, 2: {"success": 1}},
    )

    panel.load_history_async(7)

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not panel._all_histories:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()

    assert len(panel._all_histories) == 2, "后台查询结果应回传 GUI 线程并渲染"
    assert panel._workflow_id == 7
    assert panel.table.rowCount() == 2
    assert app is not None
