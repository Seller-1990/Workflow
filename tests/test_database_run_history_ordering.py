# -*- coding: utf-8 -*-
"""RunHistory ordering contracts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _schema_guard_utils import _use_temp_database


def test_run_history_list_uses_insert_order_for_latest(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("运行历史排序")
    older = db.create_run_history(workflow.id)
    newer = db.create_run_history(workflow.id)

    db.update_run_history(
        older.id,
        status="success",
        start_time=datetime(2026, 7, 8, 12, 0, 0),
        end_time=datetime(2026, 7, 8, 12, 1, 0),
    )
    db.update_run_history(
        newer.id,
        status="success",
        start_time=datetime(2026, 7, 8, 11, 0, 0),
        end_time=datetime(2026, 7, 8, 11, 1, 0),
    )

    histories = db.get_run_histories_by_workflow(workflow.id, limit=10)

    assert [history.id for history in histories] == [newer.id, older.id]


def test_latest_run_history_uses_insert_order_for_latest(monkeypatch, tmp_path: Path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("最近运行排序")
    older = db.create_run_history(workflow.id)
    newer = db.create_run_history(workflow.id)

    db.update_run_history(
        older.id,
        status="success",
        start_time=datetime(2026, 7, 8, 12, 0, 0),
        end_time=datetime(2026, 7, 8, 12, 1, 0),
    )
    db.update_run_history(
        newer.id,
        status="failure",
        start_time=datetime(2026, 7, 8, 11, 0, 0),
        end_time=datetime(2026, 7, 8, 11, 1, 0),
    )

    latest = db.get_latest_run_history(workflow.id, only_finished=True)

    assert latest.id == newer.id
