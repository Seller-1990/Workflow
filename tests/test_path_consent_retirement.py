# -*- coding: utf-8 -*-
"""路径确认退役：真实选步/快照和普通配置校验仍是执行契约。"""

import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from _schema_guard_utils import _use_temp_database
from engine import RunMode, RunSignalPolicy, WorkflowEngine
from risk_path_review import StepSnapshot, WorkflowView


@pytest.fixture
def imported_run(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    script = tmp_path / "safe_demo.py"
    script.write_text("print('local safe demo')\n", encoding="utf-8")
    payload = tmp_path / "workflow.json"
    payload.write_text(json.dumps({
        "version": 1,
        "workflows": [{
            "id": "retired-consent", "name": "无需路径二次确认",
            "steps": [{
                "id": f"s{index}", "name": f"步骤{index}",
                "step_type": "python", "script": str(script),
                "cwd": str(tmp_path), "order": index,
            } for index in range(1, 4)],
        }],
    }), encoding="utf-8")
    assert db.import_from_json(payload) == 1
    workflow = db.get_workflow_by_uid("retired-consent")
    steps = db.get_steps_by_workflow(workflow.id)
    assert workflow.risky_paths_review_required is True
    engine = WorkflowEngine()
    logs = []
    monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(engine, "_cleanup_old_logs_async", lambda _workflow: None)
    monkeypatch.setattr(engine, "_emit_log", logs.append)
    try:
        yield SimpleNamespace(db=db, workflow=workflow, steps=steps, engine=engine, logs=logs)
    finally:
        engine.shutdown(wait=True)
        db.cleanup_session()


@pytest.mark.parametrize("legacy_digest", [None, "outdated-global", "scoped-v1:outdated"])
@pytest.mark.parametrize("mode_name", ["full", "only_step", "from_step", "step_range", "only_stage", "from_stage", "retry_failed"])
def test_all_engine_scopes_execute_without_consent_or_trust_write(imported_run, monkeypatch, legacy_digest, mode_name):
    case = imported_run
    db, workflow, steps = case.db, case.workflow, case.steps
    with db.get_session() as session:
        session.query(db.Workflow).filter_by(id=workflow.id).update({
            db.Workflow.risky_paths_confirmed_digest: legacy_digest,
        })
        session.commit()
    before = db.get_workflow_by_id(workflow.id)
    trust_before = (before.risky_paths_review_required, before.risky_paths_revision, before.risky_paths_confirmed_digest)
    selected_ids = [step.id for step in steps]
    kwargs = {}
    if mode_name in {"only_step", "from_step", "step_range"}:
        kwargs["step_id"] = steps[1].id
        selected_ids = [steps[1].id] if mode_name == "only_step" else [step.id for step in steps[1:]]
    if mode_name == "step_range":
        kwargs["end_step_id"] = steps[2].id
    if mode_name in {"only_stage", "from_stage"}:
        kwargs["stage_uid"] = steps[0].stage_uid
    if mode_name == "retry_failed":
        history = db.create_run_history(workflow.id)
        db.update_run_history(history.id, status="failure", end_time=datetime.now())
        row = db.create_step_log(history.id, steps[1].id)
        db.update_step_log(row.id, status="failure")
        selected_ids = [steps[1].id]
    reached = []

    def execute_snapshot(current_workflow, selected, _run_id, _log_dir, **_kwargs):
        reached.append((current_workflow, list(selected)))
        return True

    monkeypatch.setattr(case.engine, "_execute_steps", execute_snapshot)
    monkeypatch.setattr(db, "confirm_risky_paths", MagicMock(side_effect=AssertionError("must not persist trust")))
    policy = RunSignalPolicy(send_notification=False)
    ok = case.engine.run(workflow.id, RunMode(mode_name), reason="watch", signal_policy=policy, **kwargs)

    assert len(reached) == 1, case.logs  # outside the engine's exception boundary
    assert ok is True
    executed_workflow, selected = reached[0]
    assert isinstance(executed_workflow, WorkflowView)
    assert all(isinstance(step, StepSnapshot) for step in selected)
    assert [step.id for step in selected] == selected_ids
    db.confirm_risky_paths.assert_not_called()
    after = db.get_workflow_by_id(workflow.id)
    assert (after.risky_paths_review_required, after.risky_paths_revision, after.risky_paths_confirmed_digest) == trust_before
    assert not any("请重新确认" in message or "未经确认" in message for message in case.logs)


@pytest.mark.parametrize("problem", ["missing_file", "malformed_args", "missing_step", "missing_range_end", "missing_stage", "retry_without_history"])
def test_retirement_keeps_ordinary_execution_failures(imported_run, monkeypatch, problem):
    case = imported_run
    db, steps = case.db, case.steps
    mode, kwargs = RunMode.ONLY_STEP, {"step_id": steps[0].id}
    expected = "不存在"
    if problem == "missing_file":
        db.update_step(steps[0].id, script_path=str(Path(steps[0].script_path).with_name("missing.py")))
    elif problem == "malformed_args":
        db.update_step(steps[0].id, args=json.dumps(["invalid\x00argument"]))
        expected = "参数"
    elif problem == "missing_step":
        kwargs["step_id"] = 99999
        expected = "未找到步骤"
    elif problem == "missing_range_end":
        mode = RunMode.STEP_RANGE
        kwargs["end_step_id"] = 99999
        expected = "未找到步骤"
    elif problem == "missing_stage":
        mode, kwargs = RunMode.ONLY_STAGE, {"stage_uid": "missing-stage"}
        expected = "阶段"
    else:
        mode, kwargs = RunMode.RETRY_FAILED, {}
        expected = "没有历史运行记录"
    ok = case.engine.run(case.workflow.id, mode, signal_policy=RunSignalPolicy(send_notification=False), **kwargs)
    assert ok is False
    details = "\n".join(case.logs)
    if problem in {"missing_file", "malformed_args"}:
        history = db.get_latest_run_history(case.workflow.id)
        assert history is not None
        rows = db.get_step_logs_by_run(history.id)
        assert len(rows) == 1 and rows[0].status == "failure"
        details += "\n" + (rows[0].error_message or "")
    assert expected in details
    assert "未经确认" not in details


@pytest.mark.parametrize("legacy_flag", [False, True])
def test_cli_commands_do_not_ask_or_write_path_consent(monkeypatch, legacy_flag):
    import cli
    import database

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "resolve_workflow_id", lambda _value: 42)
    monkeypatch.setattr(cli, "resolve_step_id", lambda _workflow_id, _value: 7)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    input_spy = MagicMock(side_effect=AssertionError("must not ask for path consent"))
    monkeypatch.setattr("builtins.input", input_spy)
    confirm = MagicMock(side_effect=AssertionError("must not persist path consent"))
    monkeypatch.setattr(database, "confirm_risky_paths", confirm)
    runner = SimpleNamespace(run=MagicMock(return_value=True), close=MagicMock())
    monkeypatch.setattr(cli, "CLIEngine", lambda: runner)
    args = SimpleNamespace(workflow_id="wf", from_step=None, to_step=None,
                           stage=None, from_stage=None, only_step="step", confirm_risky_paths=legacy_flag)
    with pytest.raises(SystemExit) as error:
        cli.cmd_run(args)
    assert error.value.code == 0
    runner.run.assert_called_once_with(42, mode="only_step", step_id=7, stage_uid=None)
    runner.close.assert_called_once_with()
    input_spy.assert_not_called()
    confirm.assert_not_called()
