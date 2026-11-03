# -*- coding: utf-8 -*-
"""单步会话参数选项与退役路径确认的真实 DB/UI 交接测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication

import ui.step_editor as step_editor_mod
import ui.step_editor_io as step_editor_io_mod
from _schema_guard_utils import _use_temp_database
from risk_path_review import StepSnapshot
from ui.step_editor import StepEditorPanel


def _step(step_id: int):
    return SimpleNamespace(
        id=step_id, workflow_id=7, uid=f"step-{step_id}", name=f"步骤{step_id}",
        order=step_id, step_type="python", script_path="scripts/run.py",
        args=None, saved_run_args=None, cwd=None, chart_theme=None,
        timeout_seconds=None, retry_count=0, is_gate=False,
        skip_on_success=False, stage_uid=None,
        get_output_paths=lambda: [], get_depends_on=lambda: [],
    )


def _load_step(monkeypatch, step_id: int):
    step = _step(step_id)
    for mod in (step_editor_mod, step_editor_io_mod):
        monkeypatch.setattr(mod, "get_step_by_id", lambda _sid, s=step: s)
        monkeypatch.setattr(mod, "get_steps_by_workflow", lambda _wid: [])
        monkeypatch.setattr(mod, "list_stages", lambda _wid: [])
        monkeypatch.setattr(mod, "list_workflows", lambda: [])
    monkeypatch.setattr(step_editor_mod, "get_stage_order_map", lambda _wid: {})


def test_modify_args_checkbox_is_session_state_not_step_configuration(monkeypatch):
    QApplication.instance() or QApplication([])
    panel = StepEditorPanel()
    try:
        _load_step(monkeypatch, 1)
        panel.load_step(1)
        assert panel.check_modify_run_args.text() == "本次修改参数"
        assert panel.check_modify_run_args.isChecked() is False
        assert panel.should_modify_run_args() is False
        assert panel.check_modify_run_args in panel.btn_run_only_step.parentWidget().findChildren(
            type(panel.check_modify_run_args)
        )
        panel.check_modify_run_args.setChecked(True)
        panel.load_step(1)
        assert panel.should_modify_run_args() is True
        assert panel.is_dirty() is False
        panel.clear()
        assert panel.should_modify_run_args() is True
        _load_step(monkeypatch, 2)
        panel.load_step(2)
        assert panel.should_modify_run_args() is True
        panel.check_modify_run_args.setChecked(False)
        assert panel.should_modify_run_args() is False
        assert panel.is_dirty() is False
    finally:
        panel.close()


@pytest.mark.parametrize("digest", [None, "stale-global", "scoped-v1:stale"])
def test_ui_handoff_reaches_real_engine_without_path_question_or_trust_write(monkeypatch, tmp_path, digest):
    from engine import RunMode, RunSignalPolicy, WorkflowEngine
    from ui import run_dispatch as rd
    from test_risk_path_review import _import_two_risky_steps

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow, steps = _import_two_risky_steps(db, tmp_path)
    with db.get_session() as session:
        session.query(db.Workflow).filter_by(id=workflow.id).update({
            db.Workflow.risky_paths_confirmed_digest: digest,
        })
        session.commit()
    before = db.get_workflow_by_id(workflow.id)
    trust_before = (before.risky_paths_review_required, before.risky_paths_revision, before.risky_paths_confirmed_digest)
    engine = WorkflowEngine()
    executed = []
    worker_results = []
    logs = []
    monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(engine, "_cleanup_old_logs_async", lambda _workflow: None)
    monkeypatch.setattr(engine, "_emit_log", logs.append)

    def execute(_workflow, selected, _run_id, _log_dir, **_kwargs):
        executed.append(list(selected))
        return True

    monkeypatch.setattr(engine, "_execute_steps", execute)
    question = MagicMock(side_effect=AssertionError("retired question must not be shown"))
    monkeypatch.setattr("ui.theme.msg_question", question)
    confirm = MagicMock(side_effect=AssertionError("normal run must not persist trust"))
    monkeypatch.setattr(db, "confirm_risky_paths", confirm)

    class InlineWorker:
        """Exercise dispatcher -> real engine handoff without starting a Qt thread."""
        def __init__(self, current_engine, *, workflow_id, mode, param, run_arg_overrides):
            self.kwargs = dict(workflow_id=workflow_id, mode=mode, param=param, run_arg_overrides=run_arg_overrides)
            self.engine = current_engine

        def start(self):
            worker_results.append(self.engine.run(
                self.kwargs["workflow_id"], RunMode(self.kwargs["mode"]),
                step_id=self.kwargs["param"],
                run_arg_overrides=self.kwargs["run_arg_overrides"],
                signal_policy=RunSignalPolicy(send_notification=False),
            ))

    monkeypatch.setattr(rd, "RunWorker", InlineWorker)
    window = SimpleNamespace(_current_workflow_id=workflow.id, _dark_mode=False, engine=engine)
    try:
        for selected in steps:
            rd.on_run_requested(window, "only_step", selected.id)
        rd.on_run_requested(window, "full", None)
        assert worker_results == [True, True, True], logs
        assert [[step.id for step in selected] for selected in executed] == [
            [steps[0].id], [steps[1].id], [step.id for step in steps],
        ]
        assert all(isinstance(step, StepSnapshot) for selection in executed for step in selection)
        question.assert_not_called()
        confirm.assert_not_called()
        after = db.get_workflow_by_id(workflow.id)
        assert (after.risky_paths_review_required, after.risky_paths_revision, after.risky_paths_confirmed_digest) == trust_before
    finally:
        engine.shutdown(wait=True)
        db.cleanup_session()
