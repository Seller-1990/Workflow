# -*- coding: utf-8 -*-
"""Current execution policy: legacy path metadata never requires renewed consent.

Real CLI/import-and-run child processes remain here at the reviewed subprocess
boundary. Legacy metadata and immutable execution data have independent suites.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
CLI_SCRIPT = SRC_DIR / "cli.py"
IMPORT_AND_RUN_SCRIPT = ROOT_DIR / "_import_and_run.py"
WORKFLOW_APP_DATA_DIR_ENV = "WORKFLOW_APP_DATA_DIR"

sys.path.insert(0, str(SRC_DIR))

import database
import risk_path_review
from _risk_review_test_utils import _import_two_risky_steps, _risky_steps, _wf
from risk_path_review import build_run_plan, collect_risk_paths, compute_digest, evaluate_run_plan


@pytest.mark.parametrize("review_required", [False, True])
@pytest.mark.parametrize("digest", [None, "stale-global", "scoped-v1:stale"])
def test_evaluate_run_plan_is_legacy_noop(review_required, digest):
    workflow = _wf(risky_paths_review_required=review_required,
                   risky_paths_revision=7, risky_paths_confirmed_digest=digest)
    for steps in ([], _risky_steps()):
        plan = build_run_plan(workflow, steps)
        assert evaluate_run_plan(plan) is None
        assert plan.review_required is review_required
        assert plan.confirmed_digest == digest


def test_legacy_scoped_digest_does_not_authorize_or_block_selection():
    steps = [
        SimpleNamespace(id=1, uid="a", script_path="C:/a.py", cwd=None),
        SimpleNamespace(id=2, uid="b", script_path="D:/b.py", cwd=None),
    ]
    workflow = _wf(risky_paths_review_required=True, risky_paths_revision=3)
    scope = [steps[0]]
    workflow.risky_paths_confirmed_digest = risk_path_review.compute_scoped_confirmation_digest(
        3, ["a"], collect_risk_paths(scope)
    )

    for selected in (scope, [steps[1]], steps):
        plan = build_run_plan(workflow, steps, selected_steps=selected)
        assert evaluate_run_plan(plan) is None
        assert set(plan.step_snapshots) == {1, 2}
        assert plan.selected_step_uids == tuple(step.uid for step in selected)

    workflow.risky_paths_revision = 4
    assert evaluate_run_plan(build_run_plan(workflow, steps, selected_steps=scope)) is None

    # 旧状态仍可读取，但不再影响任意范围的运行资格。
    workflow.risky_paths_revision = 3
    assert evaluate_run_plan(build_run_plan(workflow, steps)) is None

    safe = SimpleNamespace(id=3, uid="safe", script_path="scripts/safe.py", cwd=None)
    assert evaluate_run_plan(build_run_plan(workflow, steps + [safe], selected_steps=[safe])) is None


def test_legacy_global_confirmation_still_authorizes_scoped_engine_plan():
    steps = _risky_steps()
    records = collect_risk_paths(steps)
    workflow = _wf(
        risky_paths_review_required=False, risky_paths_revision=7,
        risky_paths_confirmed_digest=compute_digest(7, records),
    )
    assert evaluate_run_plan(build_run_plan(workflow, steps, selected_steps=steps)) is None


def _make_engine_run_test(monkeypatch, tmp_path, workflow_fields, steps, fake_result=None):
    """组装 WorkflowEngine 运行环境（模块级 late-bound 补丁），返回 (engine, logs)。"""
    from engine import RunMode, WorkflowEngine

    engine = WorkflowEngine()
    logs = []
    executed = []

    def fake_execute_steps(
        current_workflow, selected_steps, run_history_id, log_dir,
        signal_policy, run_cancel_event=None, run_arg_overrides=None,
    ):
        executed.append((run_history_id, len(selected_steps)))
        return True if fake_result is None else fake_result

    monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path)
    monkeypatch.setattr(
        "engine.get_workflow_by_id",
        lambda workflow_id: workflow_fields.get("workflow") if workflow_id == 1 else None,
    )
    monkeypatch.setattr(
        "engine.get_steps_by_workflow",
        lambda workflow_id: steps if workflow_id == 1 else [],
    )
    monkeypatch.setattr(
        "engine_core.lifecycle.create_run_history",
        lambda **kwargs: SimpleNamespace(
            id=11, run_id="run-1", trace_id=kwargs.get("trace_id") or "trace-1",
            parent_run_id=kwargs.get("parent_run_id"),
        ),
    )
    monkeypatch.setattr("engine_core.lifecycle.update_run_history", lambda *a, **k: None)
    monkeypatch.setattr("engine.update_run_history", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
    monkeypatch.setattr(engine, "_select_steps", lambda *a, **k: steps)
    monkeypatch.setattr(engine, "_emit_log", lambda message: logs.append(message))
    monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)
    return engine, logs, executed


@pytest.mark.parametrize("review_required", [False, True])
@pytest.mark.parametrize("digest", [None, "outdated-global", "scoped-v1:outdated"])
def test_engine_ignores_legacy_review_state(monkeypatch, tmp_path, review_required, digest):
    from engine import RunMode

    workflow = SimpleNamespace(
        id=1, uid="wf-1", name="主工作流", log_retention_days=1,
        single_script_enabled=False, parallel_enabled=False,
        get_notify_config=lambda: {},
        risky_paths_review_required=review_required, risky_paths_revision=9,
        risky_paths_confirmed_digest=digest,
    )
    steps = [SimpleNamespace(
        id=1, uid="step-a", order=1, name="A", step_type="python",
        script_path="C:/fake-execution.py", cwd=None,
    )]
    engine, logs, executed = _make_engine_run_test(monkeypatch, tmp_path, {"workflow": workflow}, steps)
    try:
        assert engine.run(1, RunMode.FULL) is True
        assert executed == [(11, 1)]
        assert not any("未经确认" in message or "请重新确认" in message for message in logs)
    finally:
        engine.shutdown(wait=False)


def test_engine_run_allowed_when_no_risk_records(monkeypatch, tmp_path):
    from engine import RunMode, WorkflowEngine

    engine = WorkflowEngine()
    try:
        steps = [SimpleNamespace(
            id=1, uid="step-a", order=1, name="A",
            step_type="python", script_path="scripts/run.py", cwd=None,
        )]
        workflow = SimpleNamespace(
            id=1, uid="wf-1", name="主工作流", log_retention_days=1,
            single_script_enabled=False, parallel_enabled=False,
            get_notify_config=lambda: {},
            risky_paths_review_required=0, risky_paths_revision=0,
            risky_paths_confirmed_digest=None,
        )
        engine, logs, executed = _make_engine_run_test(monkeypatch, tmp_path, {"workflow": workflow}, steps)

        ok = engine.run(1, RunMode.FULL)
        assert ok is True
        assert executed == [(11, 1)]
    finally:
        engine.shutdown(wait=False)


@pytest.mark.parametrize("is_tty", [False, True])
@pytest.mark.parametrize("legacy_flag", [False, True])
def test_cli_run_and_retry_skip_consent_in_every_terminal(monkeypatch, is_tty, legacy_flag):
    import cli
    from unittest.mock import MagicMock

    monkeypatch.setattr(cli, "init_db", lambda: None)
    monkeypatch.setattr(cli, "resolve_workflow_id", lambda _value: 42)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: is_tty))
    ask = MagicMock(side_effect=EOFError)
    monkeypatch.setattr("builtins.input", ask)
    confirm = MagicMock(side_effect=AssertionError("normal runs must not persist trust"))
    monkeypatch.setattr(database, "confirm_risky_paths", confirm)
    runner = SimpleNamespace(run=MagicMock(return_value=True), close=MagicMock())
    monkeypatch.setattr(cli, "CLIEngine", lambda: runner)
    args = SimpleNamespace(workflow_id="wf", from_step=None, to_step=None, stage=None,
                           from_stage=None, only_step=None, confirm_risky_paths=legacy_flag)
    for command in (cli.cmd_run, cli.cmd_retry):
        with pytest.raises(SystemExit) as error:
            command(args)
        assert error.value.code == 0
    assert runner.run.call_count == 2
    assert runner.close.call_count == 2
    ask.assert_not_called()
    confirm.assert_not_called()


def _build_subprocess_env(app_data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env[WORKFLOW_APP_DATA_DIR_ENV] = str(app_data_dir)
    return env


def _run_python(app_data_dir: Path, *args, cwd: Path = ROOT_DIR) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=_build_subprocess_env(app_data_dir),
        cwd=cwd,
        # 显式提供空 stdin：子进程 isatty()=False，走非 TTY 门禁路径
        input="",
    )


def _write_risky_payload(tmp_path: Path, *, uid: str = "wf_cli_risky", name: str = "CLI风险工作流") -> Path:
    script = tmp_path / "ok_step.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    payload = tmp_path / f"{uid}.json"
    payload.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": uid,
                        "name": name,
                        "description": "CLI 风险",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "Step",
                                "step_type": "python",
                                "script": str(script),
                                "cwd": str(tmp_path),
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return payload


def _seed_import_and_get_id(app_data_dir: Path, payload: Path, name: str) -> int:
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path.cwd() / 'src'))\n"
        "from database import init_db, import_from_json_with_warnings, get_workflow_by_name\n"
        "init_db()\n"
        "result = import_from_json_with_warnings(sys.argv[1])\n"
        "wf = get_workflow_by_name(sys.argv[2])\n"
        "print(wf.id)\n"
        "sys.exit(0 if result.imported_count == 1 else 2)\n"
    )
    result = _run_python(
        app_data_dir, "-c", code, payload, name,
        cwd=ROOT_DIR,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.strip().splitlines()[-1])


def _assert_subprocess_legacy_trust_unchanged(app_data_dir, workflow_id):
    import sqlite3

    with sqlite3.connect(app_data_dir / "data/workflows.db") as connection:
        state = connection.execute(
            "SELECT risky_paths_review_required, risky_paths_confirmed_digest "
            "FROM workflows WHERE id = ?", (workflow_id,),
        ).fetchone()
    assert state == (1, None)


def test_cli_run_risky_executes_non_tty_without_flag(tmp_path):
    app_data_dir = tmp_path / "cli-run-app-data"
    payload = _write_risky_payload(tmp_path)
    workflow_id = _seed_import_and_get_id(app_data_dir, payload, "CLI风险工作流")

    result = _run_python(app_data_dir, CLI_SCRIPT, "run", str(workflow_id))

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "工作流结束" in output and "成功" in output
    assert "未经确认的风险路径" not in output
    assert "非交互环境请显式使用" not in output
    _assert_subprocess_legacy_trust_unchanged(app_data_dir, workflow_id)


def test_cli_run_risky_legacy_flag_is_noop(tmp_path):
    app_data_dir = tmp_path / "cli-run-flag-app-data"
    payload = _write_risky_payload(tmp_path)
    workflow_id = _seed_import_and_get_id(app_data_dir, payload, "CLI风险工作流")

    result = _run_python(app_data_dir, CLI_SCRIPT, "run", str(workflow_id), "--confirm-risky-paths")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "工作流结束" in output
    assert "成功" in output
    _assert_subprocess_legacy_trust_unchanged(app_data_dir, workflow_id)


def test_cli_retry_without_history_reports_original_error_not_consent(tmp_path):
    app_data_dir = tmp_path / "cli-retry-app-data"
    payload = _write_risky_payload(tmp_path)
    workflow_id = _seed_import_and_get_id(app_data_dir, payload, "CLI风险工作流")

    result = _run_python(app_data_dir, CLI_SCRIPT, "retry", str(workflow_id))

    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "没有历史运行记录" in output
    assert "未经确认的风险路径" not in output
    assert "--confirm-risky-paths" not in output


def _write_import_and_run_payload(tmp_path: Path, *, name: str = "月度数据处理") -> Path:
    script = tmp_path / "ok_auto.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    payload = tmp_path / "iar.json"
    payload.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_iar",
                        "name": name,
                        "description": "自动运行",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "Step",
                                "step_type": "python",
                                "script": str(script),
                                "cwd": str(tmp_path),
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return payload


def test_import_and_run_run_executes_without_flag(tmp_path):
    app_data_dir = tmp_path / "iar-run-app-data"
    payload = _write_import_and_run_payload(tmp_path)

    imported = _run_python(
        app_data_dir,
        IMPORT_AND_RUN_SCRIPT, "--workflows-json", payload, "import",
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    result = _run_python(
        app_data_dir,
        IMPORT_AND_RUN_SCRIPT, "--workflows-json", payload, "run", "月度数据处理",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "工作流结束" in output and "成功" in output
    assert "未经确认的风险路径" not in output


def test_import_and_run_run_with_flag_succeeds(tmp_path):
    app_data_dir = tmp_path / "iar-run-flag-app-data"
    payload = _write_import_and_run_payload(tmp_path)

    imported = _run_python(
        app_data_dir,
        IMPORT_AND_RUN_SCRIPT, "--workflows-json", payload, "import",
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr

    result = _run_python(
        app_data_dir,
        IMPORT_AND_RUN_SCRIPT, "--workflows-json", payload,
        "run", "月度数据处理", "--confirm-risky-paths",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "工作流结束" in output
    assert "成功" in output


def test_import_and_run_auto_same_gate_auto_confirms(tmp_path):
    """--auto 同一门禁：自动确认后执行（非交互环境无需再指定 flag）。"""
    app_data_dir = tmp_path / "iar-auto-app-data"
    payload = _write_import_and_run_payload(tmp_path)

    result = _run_python(
        app_data_dir,
        IMPORT_AND_RUN_SCRIPT, "--workflows-json", payload, "--auto",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "导入完成: 1 个工作流" in output
    assert "工作流结束" in output
    assert "成功" in output
