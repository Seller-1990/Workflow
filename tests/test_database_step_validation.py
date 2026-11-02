# -*- coding: utf-8 -*-
"""One numeric contract, with import paths and pre-session update diagnostics."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import database
import database_workflows
from database_import_validation import validate_import_payload
from database_step_validation import expect_int_if_present


@pytest.mark.parametrize("field", ["retry_count", "timeout_seconds"])
@pytest.mark.parametrize(
    ("value", "message"),
    [
        (-1, "必须是非负整数"),
        (True, "必须是整数"),
        (False, "必须是整数"),
        (1.5, "必须是整数"),
        ("1", "必须是整数"),
        ([], "必须是整数"),
        ({}, "必须是整数"),
    ],
)
def test_runtime_limits_reject_same_values_at_import_and_update(monkeypatch, field, value, message):
    payload = {"version": 1, "workflows": [{"steps": [{field: value}]}]}
    with pytest.raises(ValueError) as import_error:
        validate_import_payload(payload)
    assert str(import_error.value) == f"$.workflows[0].steps[0].{field}: {message}"

    session_factory = MagicMock(side_effect=AssertionError("invalid fields must not open a session"))
    monkeypatch.setattr(database, "get_session", session_factory)
    with pytest.raises(ValueError) as update_error:
        database_workflows.update_step(1, **{field: value})
    assert str(update_error.value) == f"{field} 必须是非负整数或 None"
    session_factory.assert_not_called()


@pytest.mark.parametrize("field", ["retry_count", "timeout_seconds"])
@pytest.mark.parametrize("value", [None, 0, 12])
def test_runtime_limits_accept_optional_nonnegative_integers(monkeypatch, field, value):
    payload = {"version": 1, "workflows": [{"steps": [{field: value}]}]}
    assert validate_import_payload(payload) is payload

    step = SimpleNamespace(id=1)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = step
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = session
    invalidate = MagicMock()
    monkeypatch.setattr(database, "get_session", session_factory)
    monkeypatch.setattr(database, "invalidate_cycle_check_cache", invalidate)

    assert database_workflows.update_step(1, **{field: value}) is step
    assert getattr(step, field) == value
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(step)
    invalidate.assert_called_once_with()


def test_step_update_keeps_whitelist_validation_before_numeric_error(monkeypatch):
    session_factory = MagicMock(side_effect=AssertionError("unknown fields must not open a session"))
    monkeypatch.setattr(database, "get_session", session_factory)
    with pytest.raises(ValueError, match="Step 不支持更新字段: unknown"):
        database_workflows.update_step(1, unknown=3, retry_count=-1)
    session_factory.assert_not_called()


def test_step_update_keeps_late_bound_field_guard_and_allowlist(monkeypatch):
    allowed = {"retry_count"}
    guard = MagicMock(side_effect=ValueError("patched guard"))
    monkeypatch.setattr(database_workflows, "STEP_UPDATE_FIELDS", allowed)
    monkeypatch.setattr(database_workflows, "_validate_update_fields", guard)
    with pytest.raises(ValueError, match="patched guard"):
        database_workflows.update_step(1, retry_count=0)
    guard.assert_called_once_with("Step", {"retry_count": 0}, allowed)


@pytest.mark.parametrize("allow_none", [False, True])
def test_general_integer_import_contract_keeps_missing_nullable_and_bool_behavior(allow_none):
    expect_int_if_present({}, "order", "$.stage", allow_none=allow_none)
    expect_int_if_present({"order": -1}, "order", "$.stage", allow_none=allow_none)
    if allow_none:
        expect_int_if_present({"order": None}, "order", "$.stage", allow_none=True)
    else:
        with pytest.raises(ValueError, match=r"\$\.stage.order: 必须是整数"):
            expect_int_if_present({"order": None}, "order", "$.stage")
    with pytest.raises(ValueError, match=r"\$\.stage.order: 必须是整数"):
        expect_int_if_present({"order": True}, "order", "$.stage", allow_none=allow_none)
