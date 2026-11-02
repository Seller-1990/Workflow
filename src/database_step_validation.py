# -*- coding: utf-8 -*-
"""Shared integer field contracts for workflow imports and step runtime limits."""

from __future__ import annotations

from database_field_guards import STEP_UPDATE_FIELDS, validate_update_fields


def _integer_error(value, *, allow_none: bool = False) -> str | None:
    if allow_none and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return "必须是整数"
    return None


def _non_negative_int_error(value) -> str | None:
    type_error = _integer_error(value, allow_none=True)
    if type_error:
        return type_error
    if value is not None and value < 0:
        return "必须是非负整数"
    return None


def expect_int_if_present(parent: dict, key: str, path: str, *, allow_none: bool = False) -> None:
    if key in parent:
        error = _integer_error(parent.get(key), allow_none=allow_none)
        if error:
            raise ValueError(f"{path}.{key}: {error}")


def validate_step_update_fields(
    values: dict, *, validate_fields=validate_update_fields, allowed_fields=STEP_UPDATE_FIELDS,
) -> None:
    """Reject unknown fields and invalid execution limits before opening a session."""
    validate_fields("Step", values, allowed_fields)
    for field in ("retry_count", "timeout_seconds"):
        if _non_negative_int_error(values.get(field)):
            raise ValueError(f"{field} 必须是非负整数或 None")


def expect_non_negative_int_if_present(parent: dict, key: str, path: str) -> None:
    """Keep import diagnostics field-qualified and distinguish type/range errors."""
    error = _non_negative_int_error(parent.get(key))
    if error:
        raise ValueError(f"{path}.{key}: {error}")
