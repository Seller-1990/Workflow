# -*- coding: utf-8 -*-
"""Run history pagination tests."""

import sys
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
