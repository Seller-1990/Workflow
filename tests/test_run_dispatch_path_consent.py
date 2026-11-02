# -*- coding: utf-8 -*-
"""GUI dispatch does not revive retired path-consent reads, writes or prompts."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest


SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture
def run_dispatch(monkeypatch):
    ui_pkg = ModuleType("ui")
    ui_pkg.__path__ = [str(SRC / "ui")]
    monkeypatch.setitem(sys.modules, "ui", ui_pkg)
    worker_module = ModuleType("ui.run_worker")
    worker_module.RunWorker = MagicMock()
    monkeypatch.setitem(sys.modules, "ui.run_worker", worker_module)
    theme = ModuleType("ui.theme")
    theme.msg_warning = MagicMock()
    theme.msg_question = MagicMock()
    monkeypatch.setitem(sys.modules, "ui.theme", theme)
    dialog = ModuleType("ui.script_run_args_dialog")
    dialog.prompt_run_arg_overrides = MagicMock(return_value=(True, {}, {}))
    monkeypatch.setitem(sys.modules, "ui.script_run_args_dialog", dialog)
    db = ModuleType("database")
    db.get_workflow_by_id = MagicMock()
    db.get_steps_by_workflow = MagicMock(return_value=[])
    db.confirm_risky_paths = MagicMock()
    monkeypatch.setitem(sys.modules, "database", db)
    spec = importlib.util.spec_from_file_location("ui.run_dispatch", SRC / "ui/run_dispatch.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ui.run_dispatch", module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _risky_stub_step():
    return SimpleNamespace(uid="s1", step_type="python", script_path="C:/evil.py", cwd=None)


def _risky_stub_workflow(workflow_id=42):
    return SimpleNamespace(
        id=workflow_id,
        risky_paths_review_required=1,
        risky_paths_revision=1,
        risky_paths_confirmed_digest=None,
    )


def _make_gate_window():
    return SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        engine=SimpleNamespace(is_running=False),
    )


def test_risky_gate_no_risk_skips_dialog(run_dispatch):
    rd = run_dispatch
    import database

    database.get_workflow_by_id = MagicMock(return_value=SimpleNamespace(
        id=42,
        risky_paths_review_required=0,
        risky_paths_revision=0,
        risky_paths_confirmed_digest=None,
    ))
    database.get_steps_by_workflow = MagicMock(return_value=[
        SimpleNamespace(uid="s1", step_type="python", script_path="scripts/run.py", cwd=None),
    ])
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock(return_value=None)
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    rd.on_run_requested(_make_gate_window(), "full", None)

    ui_theme.msg_question.assert_not_called()
    database.confirm_risky_paths.assert_not_called()
    rd.RunWorker.assert_called_once_with(
        rd.RunWorker.call_args.args[0],
        workflow_id=42,
        mode="full",
        param=None,
        run_arg_overrides={},
    )
    worker.start.assert_called_once_with()


def test_risky_paths_do_not_ask_or_block_worker(run_dispatch):
    rd = run_dispatch
    import database

    database.get_workflow_by_id = MagicMock(return_value=_risky_stub_workflow())
    database.get_steps_by_workflow = MagicMock(return_value=[_risky_stub_step()])
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock(side_effect=AssertionError("must not ask for consent"))
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    rd.on_run_requested(_make_gate_window(), "full", None)

    ui_theme.msg_question.assert_not_called()
    rd.RunWorker.assert_called_once()
    worker.start.assert_called_once_with()
    database.confirm_risky_paths.assert_not_called()


def test_legacy_stale_digest_does_not_trigger_read_or_trust_write(run_dispatch):
    rd = run_dispatch
    import database

    workflow = _risky_stub_workflow()
    workflow.risky_paths_confirmed_digest = "scoped-v1:stale"
    database.get_workflow_by_id = MagicMock(return_value=workflow)
    database.get_steps_by_workflow = MagicMock(return_value=[_risky_stub_step()])
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    rd.on_run_requested(_make_gate_window(), "full", None)

    database.get_workflow_by_id.assert_not_called()
    database.get_steps_by_workflow.assert_not_called()
    database.confirm_risky_paths.assert_not_called()
    assert workflow.risky_paths_confirmed_digest == "scoped-v1:stale"
    assert workflow.risky_paths_review_required == 1
    rd.RunWorker.assert_called_once()
    worker.start.assert_called_once_with()


@pytest.mark.parametrize(
    ("mode", "param"),
    [
        ("full", None),
        ("from_step", 7),
        ("only_step", 7),
        ("only_stage", "stage-1"),
        ("from_stage", "stage-1"),
        ("step_range", (7, 8)),
        ("retry_failed", None),
    ],
)
def test_all_run_modes_skip_path_confirmation(run_dispatch, mode, param):
    rd = run_dispatch
    import database

    database.get_workflow_by_id = MagicMock(return_value=_risky_stub_workflow())
    database.get_steps_by_workflow = MagicMock(return_value=[_risky_stub_step()])
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock(side_effect=AssertionError("must not ask for consent"))
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=True,
        engine=SimpleNamespace(is_running=False),
    )
    rd.on_run_requested(window, mode, param)

    ui_theme.msg_question.assert_not_called()
    rd.RunWorker.assert_called_once()
    worker.start.assert_called_once_with()
    database.confirm_risky_paths.assert_not_called()


def test_risky_gate_does_not_fire_when_workflow_missing(run_dispatch):
    rd = run_dispatch
    import database

    database.get_workflow_by_id = MagicMock(return_value=None)
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock()
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    rd.on_run_requested(_make_gate_window(), "full", None)

    ui_theme.msg_question.assert_not_called()
    rd.RunWorker.assert_called_once()
