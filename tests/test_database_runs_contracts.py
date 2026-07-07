# -*- coding: utf-8 -*-
"""Run/step log persistence contracts."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database
from database_runs import MAX_ERROR_MESSAGE_LENGTH, update_step_log


class _StepLogRow:
    error_message = None


class _Query:
    def __init__(self, row):
        self._row = row

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._row


class _Session:
    def __init__(self, row):
        self.row = row
        self.committed = False

    def query(self, _model):
        return _Query(self.row)

    def commit(self):
        self.committed = True

    def refresh(self, _row):
        return None


def test_update_step_log_truncates_large_error_message(monkeypatch):
    row = _StepLogRow()
    session = _Session(row)

    @contextmanager
    def fake_get_session():
        yield session

    monkeypatch.setattr(database, "get_session", fake_get_session)

    update_step_log(1, error_message="x" * (MAX_ERROR_MESSAGE_LENGTH + 50))

    assert session.committed is True
    assert len(row.error_message) == MAX_ERROR_MESSAGE_LENGTH
    assert row.error_message.endswith("...")
