# -*- coding: utf-8 -*-
"""CLI 输出契约测试"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cli


@dataclass
class DummyHistory:
    id: int = 1
    run_id: str = "run-001"
    status: str = "success"
    reason: str = "manual"
    start_time: datetime = datetime(2026, 1, 1, 8, 0, 0)
    end_time: datetime = datetime(2026, 1, 1, 8, 0, 5)


@dataclass
class DummyStep:
    name: str


@dataclass
class DummyStepLog:
    step_id: int
    status: str
    step: DummyStep | None = None
    error_message: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


def test_history_detail_uses_step_relationship_and_duration(monkeypatch, capsys):
    started = datetime(2026, 1, 1, 8, 0, 0)
    log = DummyStepLog(
        step_id=7,
        status="success",
        step=DummyStep("清洗数据"),
        start_time=started,
        end_time=started + timedelta(seconds=12),
    )

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "resolve_workflow_id", lambda _identifier: 1)
    monkeypatch.setattr(cli, "get_run_histories_by_workflow", lambda *_args, **_kwargs: [DummyHistory()])
    monkeypatch.setattr(cli, "get_step_logs_by_run", lambda _run_history_id: [log])

    cli.cmd_history(SimpleNamespace(workflow_id="月度报表", limit=20, detail=True))

    output = capsys.readouterr().out
    assert "清洗数据" in output
    assert "OK" in output
    assert "12s" in output
