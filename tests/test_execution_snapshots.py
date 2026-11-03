# -*- coding: utf-8 -*-
"""RunPlan snapshot data and consumption across real lifecycle commits."""

from types import SimpleNamespace

import pytest

import risk_path_review
from _schema_guard_utils import _use_temp_database
from _risk_review_test_utils import _current_plan, _import_risky_workflow, _risky_steps
from risk_path_review import RunPlan, build_run_plan, collect_risk_paths, compute_digest, evaluate_run_plan


def test_run_plan_frozen_and_has_risk_records():
    records = collect_risk_paths(_risky_steps())
    plan = RunPlan(workflow_id=1, review_required=True, revision=2, confirmed_digest="x", risk_records=tuple(records))
    assert plan.has_risk_records is True
    with pytest.raises(Exception):
        plan.risk_records = ()  # frozen dataclass 不可变
    assert RunPlan(1, False, 0, None, ()).has_risk_records is False


def test_build_run_plan_materializes_snapshots_and_views():
    """H4: RunPlan 物化执行拷贝——StepSnapshot（按 id 索引）与 WorkflowView。

    - 快照字段覆盖执行链路读取值；get_args/get_saved_run_args/get_depends_on
      与 ORM 同签名同行为。
    - depends_on 损坏数据：快照构建 lenient，访问期抛 ConfigurationError
      （保留「阻止错误调度」语义）。
    """
    steps = [
        SimpleNamespace(
            id=3, workflow_id=1, uid="s1", order=0, name="A", stage_uid="stg",
            step_type="python", script_path="C:/x.py", cwd="C:/w",
            timeout_seconds=30, retry_count=2, chart_theme=None,
            is_gate=False, skip_on_success=True,
            args='["a", "b"]', saved_run_args='["s"]', depends_on='["s0"]',
        ),
        SimpleNamespace(
            id=4, workflow_id=1, uid="s2", order=1, name="B", stage_uid=None,
            step_type="sub_workflow", script_path=None, cwd=None,
            timeout_seconds=None, retry_count=0, chart_theme="dark",
            is_gate=True, skip_on_success=False,
            args=None, saved_run_args=None, depends_on='{"bad": true}',
        ),
    ]
    workflow = SimpleNamespace(
        id=1, uid="wf-1", name="主", parallel_enabled=True, max_workers=4,
        chart_theme="default", risky_paths_review_required=False,
        risky_paths_revision=0, risky_paths_confirmed_digest=None,
    )
    plan = build_run_plan(workflow, steps)

    assert isinstance(plan.workflow_view, risk_path_review.WorkflowView)
    assert plan.workflow_view.name == "主"
    assert plan.workflow_view.parallel_enabled is True
    assert plan.workflow_view.max_workers == 4
    assert plan.workflow_view.chart_theme == "default"
    assert set(plan.step_snapshots) == {3, 4}

    snap = plan.step_snapshots[3]
    assert isinstance(snap, risk_path_review.StepSnapshot)
    assert snap.script_path == "C:/x.py"
    assert snap.cwd == "C:/w"
    assert snap.stage_uid == "stg"
    assert snap.skip_on_success is True
    assert snap.get_args() == ["a", "b"]
    assert snap.get_saved_run_args() == ["s"]
    assert snap.get_depends_on() == ["s0"]

    # depends_on 损坏数据：构建 lenient，访问期抛 ConfigurationError
    bad = plan.step_snapshots[4]
    assert bad.depends_on == '{"bad": true}'
    with pytest.raises(risk_path_review.ConfigurationError):
        bad.get_depends_on()


def test_engine_run_executes_plan_snapshot_not_fresh_db(monkeypatch, tmp_path):
    """H4(TOCTOU): 真实临时 DB + 真实 _begin_run 链路（真实 commit 使 ORM 过期）。

    快照生成后（spy 在 _begin_run 的 update_run_history 提交后调用 update_step）
    并发修改 script_path，执行收到的仍是 plan 快照旧值（StepSnapshot）；
    DB 中已是新路径。旧摘要失配不再阻断下一次运行。
    """
    import engine_core.lifecycle as lifecycle_module
    from engine import RunMode, WorkflowEngine

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)  # script="../outside.py"
    assert db.confirm_risky_paths(workflow.id) is True
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None
    workflow_id = workflow.id
    step_id = db.get_steps_by_workflow(workflow_id)[0].id

    engine = WorkflowEngine()
    try:
        captured = {}

        def fake_execute_steps(
            current_workflow, selected_steps, run_history_id, log_dir,
            signal_policy, run_cancel_event=None, run_arg_overrides=None,
        ):
            captured["workflow"] = current_workflow
            captured["steps"] = list(selected_steps)
            return True

        logs = []
        monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(engine, "_cleanup_old_logs", lambda current_workflow: None)
        monkeypatch.setattr(engine, "_emit_log", lambda message: logs.append(message))
        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)

        # spy：真实 update_run_history（含 commit）执行后，模拟并发修改 script_path
        real_update_run_history = lifecycle_module.update_run_history

        def spying_update_run_history(*args, **kwargs):
            result = real_update_run_history(*args, **kwargs)
            if kwargs.get("status") == "running":
                db.update_step(step_id, script_path="C:/changed.py")
            return result

        monkeypatch.setattr(
            "engine_core.lifecycle.update_run_history", spying_update_run_history
        )

        ok = engine.run(workflow_id, RunMode.FULL)
        assert ok is True

        # 执行收到的是 plan 快照：类型 StepSnapshot、script_path 为校验时的旧值
        assert captured["steps"]
        step_snapshot = captured["steps"][0]
        assert isinstance(step_snapshot, risk_path_review.StepSnapshot)
        assert step_snapshot.script_path == "../outside.py"
        assert isinstance(captured["workflow"], risk_path_review.WorkflowView)
        assert captured["workflow"].name == "风险路径工作流"
        assert any("开始运行工作流: 风险路径工作流" in message for message in logs)

        # DB 中已是新路径；下一次运行无需重复路径确认。
        assert db.get_steps_by_workflow(workflow_id)[0].script_path == "C:/changed.py"
        plan = _current_plan(db, workflow_id)
        assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
        assert evaluate_run_plan(plan) is None
    finally:
        engine.shutdown(wait=False)


def test_snapshot_types_remain_reexported_from_risk_facade():
    import execution_snapshots
    from exceptions import ConfigurationError

    assert risk_path_review.StepSnapshot is execution_snapshots.StepSnapshot
    assert risk_path_review.WorkflowView is execution_snapshots.WorkflowView
    assert risk_path_review.ConfigurationError is ConfigurationError


@pytest.mark.parametrize(
    ("field", "raw_value", "accessor", "warning"),
    [
        ("args", "{broken", "get_args", "步骤参数 JSON 解析失败"),
        ("saved_run_args", "{broken", "get_saved_run_args", "步骤已保存运行参数 JSON 解析失败"),
        ("saved_run_args", '["ok", 1]', "get_saved_run_args", "步骤已保存运行参数不是字符串数组"),
    ],
)
def test_snapshot_warnings_keep_late_bound_risk_facade_logger(monkeypatch, field, raw_value, accessor, warning):
    from unittest.mock import MagicMock

    logger = MagicMock()
    monkeypatch.setattr(risk_path_review, "logger", logger)
    snapshot = risk_path_review._build_step_snapshot(SimpleNamespace(uid="a", **{field: raw_value}))
    assert getattr(snapshot, accessor)() == []
    assert logger.warning.call_count == 1
    assert logger.warning.call_args.args[0].startswith(warning)


@pytest.mark.parametrize("raw_value", ["{broken", "null", "{}", '["ok", 1]'])
def test_dependency_corruption_remains_a_delayed_configuration_error(raw_value):
    snapshot = risk_path_review._build_step_snapshot(SimpleNamespace(uid="a", depends_on=raw_value))
    assert snapshot.depends_on == raw_value
    with pytest.raises(risk_path_review.ConfigurationError, match="步骤依赖"):
        snapshot.get_depends_on()


def test_build_run_plan_keeps_late_bound_materializer_seams(monkeypatch):
    from unittest.mock import MagicMock

    step_builder = MagicMock(wraps=risk_path_review._build_step_snapshot)
    workflow_builder = MagicMock(wraps=risk_path_review._build_workflow_view)
    monkeypatch.setattr(risk_path_review, "_build_step_snapshot", step_builder)
    monkeypatch.setattr(risk_path_review, "_build_workflow_view", workflow_builder)
    workflow = SimpleNamespace(id=7)
    step = SimpleNamespace(id=8, workflow_id=7)

    plan = build_run_plan(workflow, [step])

    step_builder.assert_called_once_with(step)
    workflow_builder.assert_called_once_with(workflow)
    assert plan.step_snapshots[8].workflow_id == 7
    assert plan.workflow_view.id == 7


def test_materializers_keep_late_bound_snapshot_constructor_seams(monkeypatch):
    from unittest.mock import MagicMock

    step_type = MagicMock(wraps=risk_path_review.StepSnapshot)
    workflow_type = MagicMock(wraps=risk_path_review.WorkflowView)
    monkeypatch.setattr(risk_path_review, "StepSnapshot", step_type)
    monkeypatch.setattr(risk_path_review, "WorkflowView", workflow_type)

    snapshot = risk_path_review._build_step_snapshot(SimpleNamespace(id=4))
    view = risk_path_review._build_workflow_view(SimpleNamespace(id=3))

    step_type.assert_called_once()
    workflow_type.assert_called_once()
    assert snapshot.id == 4
    assert view.id == 3
