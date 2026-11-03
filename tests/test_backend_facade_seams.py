"""Responsibility extraction preserves late-bound facade testing/customization seams."""
import pytest

import database
from engine_core import lifecycle


@pytest.mark.parametrize(("name", "expected"), (
    ("_migrate_v1_workflow_step_runhistory_columns", ["_ensure_workflow_columns", "_ensure_step_columns", "_ensure_run_history_columns"]),
    ("_migrate_v2_version_table_and_step_uid_unique", ["_ensure_version_table", "_ensure_step_uid_unique"]),
    ("_migrate_v4_workflow_version_unique", ["_ensure_version_table", "_ensure_workflow_version_unique"]),
    ("_migrate_v5_webhook_name_unique", ["_ensure_webhook_name_unique"]),
))
def test_schema_wrapper_dependencies_remain_facade_bound(monkeypatch, name, expected):
    calls = []
    for dependency in expected:
        monkeypatch.setattr(database, dependency, lambda engine, dependency=dependency: calls.append((dependency, engine)))
    target = object()
    getattr(database, name)(target)
    assert calls == [(dependency, target) for dependency in expected]


def test_legacy_skip_combination_uses_lifecycle_facade(monkeypatch):
    step = object()
    calls = []
    monkeypatch.setattr(lifecycle, "should_skip_on_success", lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.setattr(lifecycle, "record_skip_on_success", lambda **kwargs: ("recorded", kwargs))
    assert lifecycle.check_skip_on_success(step=step, run_history_id=7) == ("recorded", {"step": step, "run_history_id": 7})
    assert calls[0]["step"] is step
