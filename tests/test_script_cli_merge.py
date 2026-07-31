# -*- coding: utf-8 -*-
"""run_arg_overrides merge behavior tests."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from script_arg_utils import resolve_effective_args


def test_temporary_does_not_mutate_fixed_list():
    fixed = ["--mode", "prod"]
    overrides = {"u1": ["--year", "2025"]}
    effective = resolve_effective_args("u1", fixed, overrides)
    assert effective == ["--mode", "prod", "--year", "2025"]
    assert fixed == ["--mode", "prod"]


def test_no_override_same_as_fixed():
    fixed = ["--a", "1"]
    assert resolve_effective_args("u1", fixed, None) == ["--a", "1"]
    assert resolve_effective_args("u1", fixed, {}) == ["--a", "1"]


def test_saved_runtime_args_are_used_without_per_run_override():
    assert resolve_effective_args(
        "u1",
        ["--fixed", "1"],
        None,
        saved_run_args=["--saved", "2"],
    ) == ["--fixed", "1", "--saved", "2"]


def test_per_run_override_replaces_saved_runtime_layer():
    assert resolve_effective_args(
        "u1",
        ["--fixed", "1"],
        {"u1": ["--override", "3"]},
        saved_run_args=["--saved", "2"],
    ) == ["--fixed", "1", "--override", "3"]


def test_explicit_empty_override_suppresses_saved_runtime_layer():
    assert resolve_effective_args(
        "u1",
        ["--fixed", "1"],
        {"u1": []},
        saved_run_args=["--saved", "2"],
    ) == ["--fixed", "1"]



def test_parallel_steps_isolated_by_uid():
    """并行步骤各自按 uid 取 overrides，互不污染。"""
    overrides = {
        "step-a": ["--year", "2025"],
        "step-b": ["--mode", "dry"],
    }
    assert resolve_effective_args("step-a", ["--fixed"], overrides) == [
        "--fixed", "--year", "2025"
    ]
    assert resolve_effective_args("step-b", ["--fixed"], overrides) == [
        "--fixed", "--mode", "dry"
    ]
    assert resolve_effective_args("step-c", ["--fixed"], overrides) == ["--fixed"]


def test_empty_overrides_keeps_fixed_only():
    assert resolve_effective_args("u1", ["--a", "1"], {}) == ["--a", "1"]
