# -*- coding: utf-8 -*-
"""run_dispatch temporary CLI args collection tests.

Load run_dispatch without importing full ui/database stacks (no PySide6/sqlalchemy).
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _install_stubs(monkeypatch):
    ui_pkg = ModuleType("ui")
    ui_pkg.__path__ = [str(SRC / "ui")]
    monkeypatch.setitem(sys.modules, "ui", ui_pkg)

    rw = ModuleType("ui.run_worker")

    class RunWorker:  # noqa: N801
        pass

    rw.RunWorker = RunWorker
    monkeypatch.setitem(sys.modules, "ui.run_worker", rw)

    th = ModuleType("ui.theme")
    th.msg_warning = MagicMock()
    th.msg_question = MagicMock(return_value=None)
    monkeypatch.setitem(sys.modules, "ui.theme", th)

    dlg = ModuleType("ui.script_run_args_dialog")
    dlg.prompt_run_arg_overrides = MagicMock(return_value=(True, {}, {}))
    monkeypatch.setitem(sys.modules, "ui.script_run_args_dialog", dlg)

    db = ModuleType("database")
    db.get_workflow_by_id = MagicMock()
    db.get_steps_by_workflow = MagicMock(return_value=[])
    db.update_step = MagicMock()
    db.confirm_risky_paths = MagicMock(return_value=True)
    monkeypatch.setitem(sys.modules, "database", db)

    cfg = ModuleType("config")

    class StepType:
        PYTHON = "python"

    cfg.StepType = StepType
    monkeypatch.setitem(sys.modules, "config", cfg)

    eng = ModuleType("engine")

    class RunMode:
        FULL = "full"
        FROM_STEP = "from_step"
        ONLY_STEP = "only_step"
        ONLY_STAGE = "only_stage"
        FROM_STAGE = "from_stage"

    eng.RunMode = RunMode
    monkeypatch.setitem(sys.modules, "engine", eng)


def _load_run_dispatch(monkeypatch):
    _install_stubs(monkeypatch)
    path = SRC / "ui" / "run_dispatch.py"
    # Always reload fresh for isolation
    monkeypatch.delitem(sys.modules, "ui.run_dispatch", raising=False)
    spec = importlib.util.spec_from_file_location("ui.run_dispatch", path)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ui.run_dispatch", mod)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_collect_uses_get_workflow_by_id_not_get_workflow(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=SimpleNamespace(id=42))
    step = SimpleNamespace(
        id=7,
        uid="u1",
        name="s1",
        order=1,
        step_type="python",
        script_path="x.py",
        get_args=lambda: [],
    )
    database.get_steps_by_workflow = MagicMock(return_value=[step])

    rd.prompt_run_arg_overrides = MagicMock(
        return_value=(True, {"u1": ["--year", "2025"]}, {})
    )

    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        engine=SimpleNamespace(_select_steps=MagicMock(return_value=[step])),
    )
    result = rd._collect_run_arg_overrides(window, "full", None)

    assert result == {"u1": ["--year", "2025"]}
    database.get_workflow_by_id.assert_called_once_with(42)
    rd.prompt_run_arg_overrides.assert_called_once_with(
        window,
        [step],
        dark=False,
        is_python=rd.prompt_run_arg_overrides.call_args.kwargs["is_python"],
        allow_save_defaults=False,
    )


def test_collect_returns_none_when_user_cancels(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=SimpleNamespace(id=1))
    database.get_steps_by_workflow = MagicMock(return_value=[])
    rd.prompt_run_arg_overrides = MagicMock(return_value=(False, {}, {}))

    window = SimpleNamespace(
        _current_workflow_id=1,
        _dark_mode=False,
        engine=SimpleNamespace(),
    )
    assert rd._collect_run_arg_overrides(window, "full", None) is None


def test_collect_returns_none_when_workflow_missing(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=None)
    rd.msg_warning = MagicMock()

    window = SimpleNamespace(
        _current_workflow_id=9,
        _dark_mode=False,
        engine=SimpleNamespace(),
    )
    assert rd._collect_run_arg_overrides(window, "full", None) is None
    rd.msg_warning.assert_called_once()


def test_collect_persists_selected_saved_runtime_args_before_return(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=SimpleNamespace(id=42))
    step = SimpleNamespace(
        id=7,
        uid="u1",
        name="s1",
        order=1,
        step_type="python",
        script_path="x.py",
        get_args=lambda: [],
        get_saved_run_args=lambda: ["--old", "1"],
    )
    database.get_steps_by_workflow = MagicMock(return_value=[step])
    database.update_step = MagicMock(return_value=step)
    rd.prompt_run_arg_overrides = MagicMock(
        return_value=(True, {"u1": []}, {"u1": []})
    )
    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        _edit_mode=True,
        engine=SimpleNamespace(_select_steps=MagicMock(return_value=[step])),
    )

    result = rd._collect_run_arg_overrides(window, "only_step", step.id)

    assert result == {"u1": []}
    database.update_step.assert_called_once_with(7, saved_run_args=None)


def test_collect_blocks_saved_runtime_write_outside_edit_mode(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=SimpleNamespace(id=42))
    step = SimpleNamespace(id=7, uid="u1", step_type="python")
    database.get_steps_by_workflow = MagicMock(return_value=[step])
    database.update_step = MagicMock(return_value=step)
    rd.prompt_run_arg_overrides = MagicMock(
        return_value=(True, {"u1": ["--year", "2026"]}, {"u1": ["--year", "2026"]})
    )
    require_edit_mode = MagicMock(return_value=False)
    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        _edit_mode=False,
        _require_edit_mode=require_edit_mode,
        engine=SimpleNamespace(_select_steps=MagicMock(return_value=[step])),
    )

    result = rd._collect_run_arg_overrides(window, "only_step", step.id)

    assert result is None
    require_edit_mode.assert_called_once_with("保存运行参数")
    database.update_step.assert_not_called()


def test_only_step_preserves_explicit_empty_override_before_starting(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    overrides = {"step-1": []}
    rd._collect_run_arg_overrides = MagicMock(return_value=overrides)
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)
    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        engine=SimpleNamespace(is_running=False),
    )

    rd.on_run_requested(window, "only_step", 7)

    rd._collect_run_arg_overrides.assert_called_once_with(window, "only_step", 7)
    rd.RunWorker.assert_called_once_with(
        window.engine,
        workflow_id=42,
        mode="only_step",
        param=7,
        run_arg_overrides=overrides,
    )
    worker.start.assert_called_once_with()


def test_saved_runtime_args_failure_prevents_worker_start(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    rd._collect_run_arg_overrides = MagicMock(side_effect=RuntimeError("save failed"))
    rd.RunWorker = MagicMock()
    rd.msg_warning = MagicMock()
    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        engine=SimpleNamespace(is_running=False),
    )

    rd.on_run_requested(window, "only_step", 7)

    rd.RunWorker.assert_not_called()
    rd.msg_warning.assert_called_once()


@pytest.mark.parametrize(
    ("mode", "param"),
    [
        ("full", None),
        ("from_step", 7),
        ("only_stage", "stage-1"),
        ("from_stage", "stage-1"),
        ("retry_failed", None),
    ],
)
def test_other_run_modes_skip_temporary_args_dialog(monkeypatch, mode, param):
    rd = _load_run_dispatch(monkeypatch)
    rd._collect_run_arg_overrides = MagicMock()
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)
    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=False,
        engine=SimpleNamespace(is_running=False),
    )

    rd.on_run_requested(window, mode, param)

    rd._collect_run_arg_overrides.assert_not_called()
    rd.RunWorker.assert_called_once_with(
        window.engine,
        workflow_id=42,
        mode=mode,
        param=param,
        run_arg_overrides={},
    )
    worker.start.assert_called_once_with()


def test_source_uses_get_workflow_by_id():
    text = (SRC / "ui" / "run_dispatch.py").read_text(encoding="utf-8")
    assert "get_workflow_by_id" in text
    # bare get_workflow must not remain
    assert "get_workflow(" not in text.replace("get_workflow_by_id(", "XXX(")
    assert "无法导入 database" not in text


# ============== R1: 风险路径确认门禁（GUI 各模式） ==============

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


def test_risky_gate_no_risk_skips_dialog(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
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


def test_risky_gate_blocks_run_on_no(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=_risky_stub_workflow())
    database.get_steps_by_workflow = MagicMock(return_value=[_risky_stub_step()])
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock(return_value=None)  # 默认 No
    rd.RunWorker = MagicMock()

    rd.on_run_requested(_make_gate_window(), "full", None)

    ui_theme.msg_question.assert_called_once()
    call = ui_theme.msg_question.call_args
    assert call.args[1] is False  # dark 参数
    assert "风险路径" in call.args[2]
    assert "s1" in call.args[3] and "c:/evil.py" in call.args[3]  # 实际路径明细（规范化后）
    assert call.kwargs["default_button"] is not None
    rd.RunWorker.assert_not_called()
    database.confirm_risky_paths.assert_not_called()


def test_risky_gate_confirms_and_runs_on_yes(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=_risky_stub_workflow())
    database.get_steps_by_workflow = MagicMock(return_value=[_risky_stub_step()])
    from PySide6.QtWidgets import QMessageBox

    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock(return_value=QMessageBox.Yes)
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    rd.on_run_requested(_make_gate_window(), "full", None)

    database.confirm_risky_paths.assert_called_once_with(42)
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
        ("retry_failed", None),
    ],
)
def test_risky_gate_applies_to_all_run_modes(monkeypatch, mode, param):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=_risky_stub_workflow())
    database.get_steps_by_workflow = MagicMock(return_value=[_risky_stub_step()])
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock(return_value=None)
    rd.RunWorker = MagicMock()

    window = SimpleNamespace(
        _current_workflow_id=42,
        _dark_mode=True,
        engine=SimpleNamespace(is_running=False),
    )
    rd.on_run_requested(window, mode, param)

    ui_theme.msg_question.assert_called_once()
    assert ui_theme.msg_question.call_args.args[1] is True  # dark 透传
    rd.RunWorker.assert_not_called()
    database.confirm_risky_paths.assert_not_called()


def test_risky_gate_does_not_fire_when_workflow_missing(monkeypatch):
    rd = _load_run_dispatch(monkeypatch)
    import database

    database.get_workflow_by_id = MagicMock(return_value=None)
    ui_theme = sys.modules["ui.theme"]
    ui_theme.msg_question = MagicMock()
    worker = SimpleNamespace(start=MagicMock())
    rd.RunWorker = MagicMock(return_value=worker)

    rd.on_run_requested(_make_gate_window(), "full", None)

    ui_theme.msg_question.assert_not_called()
    rd.RunWorker.assert_called_once()
