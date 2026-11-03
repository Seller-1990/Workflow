# -*- coding: utf-8 -*-
"""区间运行（step_range：起点→终点，含两端）测试。"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import RunMode, WorkflowEngine
from engine_core.selection import select_steps
from exceptions import ConfigurationError
from ui.run_actions import run_engine_mode
from ui.run_control import compute_range_step_ids


@dataclass
class StepLike:
    id: int
    name: str
    stage_uid: str | None = None
    skip_on_success: bool = False


def _select(all_steps, mode_value, *, step_id=None, end_step_id=None, log_messages=None):
    return select_steps(
        all_steps=all_steps,
        mode_value=mode_value,
        step_id=step_id,
        end_step_id=end_step_id,
        workflow=SimpleNamespace(id=9),
        stage_uid=None,
        get_stage_order_map=lambda _wid: {},
        get_latest_run_history=lambda *a, **k: None,
        get_step_logs_by_run=lambda _rid: [],
        running_status_value="running",
        pending_status_value="pending",
        log_cb=(log_messages.append if log_messages is not None else None),
    )


def _steps():
    return [
        StepLike(1, "A", "s1"),
        StepLike(2, "B", "s1"),
        StepLike(3, "C", "s2"),
        StepLike(4, "D", "s2"),
        StepLike(5, "E", "s3"),
    ]


def _ids(steps):
    return [s.id for s in steps]


# ---------- selection ----------

def test_range_selects_inclusive_segment_only():
    assert _ids(_select(_steps(), "step_range", step_id=2, end_step_id=4)) == [2, 3, 4]


def test_range_start_equals_end_runs_single_step():
    assert _ids(_select(_steps(), "step_range", step_id=3, end_step_id=3)) == [3]


def test_range_reversed_is_swapped_and_logged():
    messages = []
    selected = _select(_steps(), "step_range", step_id=4, end_step_id=2, log_messages=messages)
    assert _ids(selected) == [2, 3, 4]
    assert messages == ["区间起点位于终点之后，已自动交换起点与终点"]


def test_range_crosses_stages_by_global_order():
    selected = _select(_steps(), "step_range", step_id=2, end_step_id=5)
    assert _ids(selected) == [2, 3, 4, 5]
    assert {s.stage_uid for s in selected} == {"s1", "s2", "s3"}


def test_range_handles_skip_steps_same_as_from_step():
    """“禁用/跳过”类步骤（skip_on_success）与 from_step 一致：选择阶段不过滤，交由执行期判定。"""
    steps = _steps()
    steps[2].skip_on_success = True
    ranged = _select(steps, "step_range", step_id=2, end_step_id=5)
    from_step = _select(steps, "from_step", step_id=2)
    assert _ids(ranged) == _ids(from_step) == [2, 3, 4, 5]
    assert ranged[1].skip_on_success is True


def test_range_unknown_step_raises():
    with pytest.raises(ConfigurationError, match="未找到步骤"):
        _select(_steps(), "step_range", step_id=2, end_step_id=99)


# ---------- engine ----------

def _patch_engine(monkeypatch, engine, tmp_path, steps, captured):
    workflow = SimpleNamespace(
        id=1, uid="wf-1", name="主工作流", log_retention_days=1,
        single_script_enabled=False, parallel_enabled=False, get_notify_config=lambda: {},
    )
    monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path)
    monkeypatch.setattr("engine.get_workflow_by_id", lambda wid: workflow if wid == 1 else None)
    monkeypatch.setattr("engine.get_steps_by_workflow", lambda wid: steps if wid == 1 else [])

    def fake_create_run_history(**kwargs):
        captured["history"] = kwargs
        return SimpleNamespace(id=11, run_id="run-1", trace_id=kwargs.get("trace_id") or "t",
                               parent_run_id=kwargs.get("parent_run_id"))

    monkeypatch.setattr("engine_core.lifecycle.create_run_history", fake_create_run_history)
    monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *a, **k: None)
    monkeypatch.setattr("engine.update_run_history", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_cleanup_old_logs", lambda wf: None)
    monkeypatch.setattr(engine, "_emit_log", lambda message: captured.setdefault("logs", []).append(message))

    def fake_execute_steps(current_workflow, selected_steps, run_history_id, log_dir, signal_policy,
                           run_cancel_event=None, run_arg_overrides=None):
        captured["executed"] = [s.id for s in selected_steps]
        captured["run_arg_overrides"] = run_arg_overrides
        return True

    monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)


def _engine_steps():
    return [SimpleNamespace(id=i, uid=f"step-{i}", order=i, name=f"S{i}", stage_uid=f"g{(i + 1) // 2}")
            for i in range(1, 6)]


def test_engine_run_range_executes_only_range_with_overrides(monkeypatch, tmp_path):
    engine = WorkflowEngine()
    try:
        captured = {}
        _patch_engine(monkeypatch, engine, tmp_path, _engine_steps(), captured)
        overrides = {"step-3": ["--year", "2025"]}
        assert engine.run_range(1, 2, 4, run_arg_overrides=overrides) is True
        assert captured["executed"] == [2, 3, 4]
        assert captured["run_arg_overrides"] == {"step-3": ["--year", "2025"]}
    finally:
        engine.shutdown(wait=False)


def test_engine_run_range_reversed_and_single(monkeypatch, tmp_path):
    engine = WorkflowEngine()
    try:
        captured = {}
        _patch_engine(monkeypatch, engine, tmp_path, _engine_steps(), captured)
        assert engine.run_range(1, 5, 3) is True
        assert captured["executed"] == [3, 4, 5]
        assert "区间起点位于终点之后，已自动交换起点与终点" in captured.get("logs", [])

        assert engine.run_range(1, 2, 2) is True
        assert captured["executed"] == [2]
    finally:
        engine.shutdown(wait=False)


def test_engine_public_run_step_range(monkeypatch, tmp_path):
    engine = WorkflowEngine()
    try:
        captured = {}
        _patch_engine(monkeypatch, engine, tmp_path, _engine_steps(), captured)
        assert engine.run(1, RunMode.STEP_RANGE, step_id=1, end_step_id=3) is True
        assert captured["executed"] == [1, 2, 3]
    finally:
        engine.shutdown(wait=False)


# ---------- UI dispatch / helper ----------

class RangeEngine:
    def __init__(self):
        self.calls = []

    def run_range(self, workflow_id, start, end, run_arg_overrides=None):
        self.calls.append((workflow_id, start, end, run_arg_overrides))
        return True


def test_run_engine_mode_step_range_forwards_overrides():
    engine = RangeEngine()
    assert run_engine_mode(engine, workflow_id=7, mode="step_range", param=(2, 4),
                           run_arg_overrides={"u": ["-x"]}) is True
    assert run_engine_mode(engine, workflow_id=7, mode="step_range", param=(4, 2)) is True
    assert engine.calls == [(7, 2, 4, {"u": ["-x"]}), (7, 4, 2, None)]


def test_compute_range_step_ids():
    ids = [10, 20, 30, 40]
    assert compute_range_step_ids(ids, 20, 40) == [20, 30, 40]
    assert compute_range_step_ids(ids, 40, 20) == [20, 30, 40]
    assert compute_range_step_ids(ids, 30, 30) == [30]
    assert compute_range_step_ids(ids, 30, 99) == []


def test_step_range_dialog_defaults():
    from PySide6.QtWidgets import QApplication
    from ui.run_control import StepRangeDialog

    _app = QApplication.instance() or QApplication([])
    steps = [SimpleNamespace(id=i, name=f"S{i}") for i in (1, 2, 3, 4)]
    dialog = StepRangeDialog(steps, default_start_id=2)
    assert dialog.selected_range() == (2, 4)
    assert dialog.lbl_count.text() == "将运行 3 个步骤"
    dialog.cmb_start.setCurrentIndex(3)
    dialog.cmb_end.setCurrentIndex(0)
    assert "将运行 4 个步骤" in dialog.lbl_count.text()
    assert "自动交换" in dialog.lbl_count.text()
    dialog.deleteLater()


# ---------- CLI ----------

def test_cli_run_from_to_dispatches_step_range(monkeypatch):
    import cli

    calls = {}
    monkeypatch.setattr(cli, "init_db", lambda: None, raising=False)
    monkeypatch.setattr(cli, "resolve_workflow_id", lambda ident: 1)
    monkeypatch.setattr(cli, "resolve_step_id", lambda wid, ident: {"B": 2, "D": 4}[ident])

    class FakeCLI:
        def run(self, workflow_id, **kwargs):
            calls["run"] = (workflow_id, kwargs)
            return True

        def close(self):
            pass

    monkeypatch.setattr(cli, "CLIEngine", FakeCLI)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "wf", "--from", "B", "--to", "D"])
    assert exc.value.code == 0
    assert calls["run"] == (1, {"mode": "step_range", "step_id": 2, "end_step_id": 4})


def test_cli_run_to_without_from_errors(monkeypatch, capsys):
    import cli

    calls = {}
    monkeypatch.setattr(cli, "init_db", lambda: calls.setdefault("init_db", True), raising=False)
    monkeypatch.setattr(cli, "resolve_workflow_id", lambda ident: 1)

    class FakeCLI:
        def run(self, workflow_id, **kwargs):
            calls["run"] = (workflow_id, kwargs)
            return True

        def close(self):
            pass

    monkeypatch.setattr(cli, "CLIEngine", FakeCLI)
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "wf", "--to", "D"])
    assert exc.value.code != 0
    assert "--to 需要与 --from 一起使用" in capsys.readouterr().err
    assert "run" not in calls  # 不得静默运行全流程
