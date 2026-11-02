# -*- coding: utf-8 -*-
"""Legacy path metadata: normalization, digests, schema upgrades and explicit writes."""

import json
import sys
from types import SimpleNamespace

import pytest

import database
import risk_path_review
from _schema_guard_utils import _use_temp_database
from _risk_review_test_utils import _current_plan, _import_risky_workflow, _import_two_risky_steps
from risk_path_review import (
    build_run_plan,
    collect_risk_paths,
    compute_digest,
    evaluate_run_plan,
    format_risk_records,
    looks_risky_path,
    normalize_path,
)


def test_normalize_path_windows_case_folding_separators_and_whitespace():
    assert normalize_path("C:\\Foo\\Bar.py", fold_case=True) == "c:/foo/bar.py"
    assert normalize_path("  C:/Foo/Bar.py  ", fold_case=True) == "c:/foo/bar.py"
    assert normalize_path("a\\b/c", fold_case=False) == "a/b/c"
    assert normalize_path("", fold_case=False) == ""
    assert normalize_path("   ", fold_case=False) == ""
    assert normalize_path(None, fold_case=False) == ""
    assert normalize_path(123, fold_case=False) == ""


def test_normalize_path_posix_preserves_case():
    # POSIX 语义：大小写保留
    assert normalize_path("/Home/User/Script.py", fold_case=False) == "/Home/User/Script.py"


def test_normalize_path_collapses_dotdot_within_bounds():
    assert normalize_path("a/../b", fold_case=False) == "b"
    assert normalize_path("a/./b", fold_case=False) == "a/b"
    assert normalize_path("a/b/../../c", fold_case=False) == "c"
    assert normalize_path("../a", fold_case=False) == "../a"
    assert normalize_path("a/../../b", fold_case=False) == "../b"
    assert normalize_path("C:/foo/..", fold_case=True) == "c:/"
    assert normalize_path("C:/../x", fold_case=True) == "c:/x"
    assert normalize_path("/../x", fold_case=False) == "/x"
    assert normalize_path("/foo/..", fold_case=False) == "/"


def test_normalize_path_unc_and_root_no_collision():
    # UNC 服务器名不可弹出；UNC 根与 POSIX 根不碰撞
    assert normalize_path("//server/share/../x", fold_case=False) == "//server/x"
    assert normalize_path("//server/..", fold_case=False) == "//server"
    assert normalize_path("//server/share/../../x", fold_case=False) == "//server/x"
    assert normalize_path("//server/share", fold_case=False) != "/"
    assert normalize_path("//server/share", fold_case=False).startswith("//")
    # 相对 `..` 与根路径不碰撞
    assert normalize_path("..", fold_case=False) == ".."
    assert normalize_path("/", fold_case=False) == "/"
    assert normalize_path("..", fold_case=False) != normalize_path("/", fold_case=False)


def test_normalize_path_fold_case_default_follows_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert normalize_path("C:\\Foo.py") == "c:/foo.py"
    monkeypatch.setattr(sys, "platform", "linux")
    assert normalize_path("C:\\Foo.py") == "C:/Foo.py"


def test_looks_risky_path_flags_absolute_and_dotdot():
    assert looks_risky_path("C:/x.py") is True
    assert looks_risky_path("C:\\x.py") is True
    assert looks_risky_path("/etc/passwd") is True
    assert looks_risky_path("\\windows\\system32") is True
    assert looks_risky_path("//server/share/x.py") is True
    assert looks_risky_path("../outside.py") is True
    assert looks_risky_path("jobs\\..\\x.py") is True


def test_looks_risky_path_safe_values():
    assert looks_risky_path("scripts/run.py") is False
    assert looks_risky_path("run.py") is False
    assert looks_risky_path("foo..bar") is False
    assert looks_risky_path("..foo") is False
    assert looks_risky_path("C:foo") is False  # 盘符相对，非绝对
    assert looks_risky_path("") is False
    assert looks_risky_path("   ") is False
    assert looks_risky_path(None) is False
    assert looks_risky_path(42) is False


def test_collect_risk_paths_from_dicts_and_objects():
    dict_steps = [
        {"id": "s1", "script": "../a.py", "cwd": "safe"},
        {"id": "s2", "script": "b.py", "cwd": "C:/jobs"},
        {"id": "s3", "script": "c.py", "cwd": "jobs"},
    ]
    records = collect_risk_paths(dict_steps)
    assert records == [
        risk_path_review.RiskRecord(step_uid="s1", field_name="script_path", path=normalize_path("../a.py")),
        risk_path_review.RiskRecord(step_uid="s2", field_name="cwd", path=normalize_path("C:/jobs")),
    ]

    obj_steps = [
        SimpleNamespace(uid="s1", step_type="python", script_path="C:\\Evil.py", cwd="safe"),
        SimpleNamespace(uid="s2", step_type="bat", script_path="ok.bat", cwd="D:/work"),
    ]
    records = collect_risk_paths(obj_steps)
    assert records == [
        risk_path_review.RiskRecord(step_uid="s1", field_name="script_path", path=normalize_path("C:\\Evil.py")),
        risk_path_review.RiskRecord(step_uid="s2", field_name="cwd", path=normalize_path("D:/work")),
    ]
    assert collect_risk_paths([]) == []
    assert collect_risk_paths(None) == []


def test_compute_digest_stable_and_order_independent():
    records = [
        risk_path_review.RiskRecord("s1", "script_path", "../a.py"),
        risk_path_review.RiskRecord("s2", "cwd", "c:/jobs"),
    ]
    d1 = compute_digest(3, records)
    d2 = compute_digest(3, list(reversed(records)))
    d3 = compute_digest(3, records)
    assert d1 == d2 == d3
    assert len(d1) == 64  # sha256 hex
    assert d1.isalnum()


def test_compute_digest_changes_with_revision_or_records():
    records = [risk_path_review.RiskRecord("s1", "script_path", "../a.py")]
    assert compute_digest(1, records) != compute_digest(2, records)
    other = [risk_path_review.RiskRecord("s1", "script_path", "../b.py")]
    assert compute_digest(1, records) != compute_digest(1, other)
    # 同路径换字段也失配
    other_field = [risk_path_review.RiskRecord("s1", "cwd", "../a.py")]
    assert compute_digest(1, records) != compute_digest(1, other_field)


def test_format_risk_records_readable():
    records = [
        risk_path_review.RiskRecord("s1", "script_path", "../a.py"),
        risk_path_review.RiskRecord("s2", "cwd", "c:/jobs"),
    ]
    text = format_risk_records(records)
    assert "s1" in text and "脚本路径" in text and "../a.py" in text
    assert "s2" in text and "工作目录" in text and "c:/jobs" in text


def _drop_risk_columns(engine):
    from sqlalchemy import text

    with engine.begin() as conn:
        for column in (
            "risky_paths_review_required",
            "risky_paths_revision",
            "risky_paths_confirmed_digest",
        ):
            conn.execute(text(f"ALTER TABLE workflows DROP COLUMN {column}"))


def _insert_legacy_workflow(db, uid: str, name: str, description: str) -> None:
    """以 v10 之前的原始 SQL 形态插入工作流（补齐所有 NOT NULL 列）。"""
    from sqlalchemy import text

    with db.get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflows (uid, name, description, chart_theme, "
                "parallel_enabled, max_workers, log_retention_days, "
                "created_at, updated_at) "
                "VALUES (:uid, :name, :description, 'default', 0, 2, "
                "30, datetime('now'), datetime('now'))"
            ),
            {"uid": uid, "name": name, "description": description},
        )


def _read_risk_state(db, uid):
    from sqlalchemy import text

    with db.get_engine().connect() as conn:
        row = conn.execute(text(
            "SELECT risky_paths_review_required, risky_paths_revision, "
            "risky_paths_confirmed_digest FROM workflows WHERE uid = :uid"
        ), {"uid": uid}).fetchone()
    return tuple(row)


def test_migrate_v10_registered_and_fresh_db_has_columns(monkeypatch, tmp_path):
    assert (10, "_migrate_v10_risky_paths_review") in database.SCHEMA_MIGRATIONS
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("全新工作流")
    assert workflow.risky_paths_review_required is False
    assert workflow.risky_paths_revision == 0
    assert workflow.risky_paths_confirmed_digest is None


def test_migrate_v10_old_db_marker_and_forged_confirmed(monkeypatch, tmp_path):
    """旧库端到端：instr 字面匹配 [导入提示]；伪造 [已确认] 不 backfill 信任。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    _drop_risk_columns(db.get_engine())

    _insert_legacy_workflow(
        db, "wf_old", "旧库",
        "说明\n[导入提示] 此工作流包含绝对路径或上级目录引用，首次运行前请确认脚本和工作目录来源可信。",
    )
    # 伪造：含 [导入提示] + [已确认]——仍不建立信任
    _insert_legacy_workflow(db, "wf_forged", "伪造", "[导入提示] 风险\n[已确认] 用户已确认导入路径安全。")
    # 无字面标记（无方括号）→ 不匹配（LIKE 会误命中字符类，instr 不会）
    _insert_legacy_workflow(db, "wf_nobracket", "无括号", "导入提示 此工作流说明")
    _insert_legacy_workflow(db, "wf_plain", "普通", "无标记")

    db._migrate_v10_risky_paths_review(db.get_engine())

    assert _read_risk_state(db, "wf_old") == (1, 0, None)
    assert _read_risk_state(db, "wf_forged") == (1, 0, None)
    assert _read_risk_state(db, "wf_nobracket") == (0, 0, None)
    assert _read_risk_state(db, "wf_plain") == (0, 0, None)


def test_migrate_v10_idempotent(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    _drop_risk_columns(db.get_engine())

    _insert_legacy_workflow(db, "wf_old", "旧库", "说明 [导入提示] 风险")
    db._migrate_v10_risky_paths_review(db.get_engine())
    db._migrate_v10_risky_paths_review(db.get_engine())  # 再跑一次幂等

    assert _read_risk_state(db, "wf_old") == (1, 0, None)
    from sqlalchemy import text

    with db.get_engine().connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(workflows)")).fetchall()
        columns = {row[1] for row in rows}
    assert {"risky_paths_review_required", "risky_paths_revision", "risky_paths_confirmed_digest"} <= columns


def test_migrate_v11_clamps_max_workers_idempotent(monkeypatch, tmp_path):
    """v11: 越界 max_workers(<1/>8)归一到边界,幂等,正常值不动。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    from sqlalchemy import text

    with db.get_engine().begin() as conn:
        conn.execute(text(
            "INSERT INTO workflows (uid, name, description, chart_theme, "
            "parallel_enabled, max_workers, log_retention_days, "
            "created_at, updated_at, "
            "risky_paths_review_required, risky_paths_revision, risky_paths_confirmed_digest) "
            "VALUES ('mw_low', '过低', NULL, 'default', 1, 0, "
            "30, datetime('now'), datetime('now'), 0, 0, NULL), "
            "('mw_high', '过高', NULL, 'default', 1, 99, "
            "30, datetime('now'), datetime('now'), 0, 0, NULL), "
            "('mw_ok', '正常', NULL, 'default', 1, 4, "
            "30, datetime('now'), datetime('now'), 0, 0, NULL)"
        ))

    db._migrate_v11_clamp_workflow_max_workers(db.get_engine())
    db._migrate_v11_clamp_workflow_max_workers(db.get_engine())  # 幂等

    with db.get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT uid, max_workers FROM workflows WHERE uid LIKE 'mw_%' ORDER BY uid"
        )).fetchall()
    assert rows == [("mw_high", 8), ("mw_low", 1), ("mw_ok", 4)]


def test_migrate_v11_registered_and_skips_when_column_missing(monkeypatch, tmp_path):
    assert (11, "_migrate_v11_clamp_workflow_max_workers") in database.SCHEMA_MIGRATIONS
    db = _use_temp_database(monkeypatch, tmp_path)
    from sqlalchemy import text

    # 手工构造无 max_workers 列的表(v11 应跳过不报错)
    with db.get_engine().begin() as conn:
        conn.execute(text("DROP TABLE workflows"))
        conn.execute(text(
            "CREATE TABLE workflows (id INTEGER PRIMARY KEY, uid VARCHAR(64) NOT NULL UNIQUE, "
            "name VARCHAR(255) NOT NULL)"
        ))
    db._migrate_v11_clamp_workflow_max_workers(db.get_engine())  # 不抛异常


def test_state_machine_import_confirm_edit_invalidate(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)

    # 导入 → review_required=1、digest 空、description 未被改写
    assert workflow.risky_paths_review_required == 1
    assert workflow.risky_paths_confirmed_digest is None
    assert workflow.description == "说明"
    revision_after_import = workflow.risky_paths_revision
    assert revision_after_import >= 1
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    # 显式旧 API 仍兼容；正常运行不再调用它。
    # 确认 → 专用事务：revision+1、digest 计算、review_required=0
    assert db.confirm_risky_paths(workflow.id) is True
    workflow = db.get_workflow_by_id(workflow.id)
    assert workflow.risky_paths_review_required == 0
    assert workflow.risky_paths_confirmed_digest is not None
    assert workflow.risky_paths_revision == revision_after_import + 1
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    # 修改后旧摘要失配仍可诊断，但不再阻断运行。
    step = db.get_steps_by_workflow(workflow.id)[0]
    db.update_step(step.id, script_path="C:/changed.py")
    workflow = db.get_workflow_by_id(workflow.id)
    assert workflow.risky_paths_revision == revision_after_import + 2
    plan = _current_plan(db, workflow.id)
    assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
    assert evaluate_run_plan(plan) is None


def test_state_machine_same_path_other_field_invalidates(monkeypatch, tmp_path):
    """同路径换字段（script_path → cwd）：确认摘要同样失配。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    step = db.get_steps_by_workflow(workflow.id)[0]
    db.update_step(step.id, cwd="C:/other-dir")
    plan = _current_plan(db, workflow.id)
    assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
    assert evaluate_run_plan(plan) is None


def test_state_machine_add_and_delete_step_invalidate(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    # 新增步骤（含风险路径）→ 失配
    db.create_step(workflow.id, "新增", script_path="D:/new.py")
    plan = _current_plan(db, workflow.id)
    assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
    assert evaluate_run_plan(plan) is None

    # 重新确认后删除风险步骤 → 失配
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None
    risky_step = db.get_step_by_name(workflow.id, "Step")
    db.delete_step(risky_step.id)
    plan = _current_plan(db, workflow.id)
    assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
    assert evaluate_run_plan(plan) is None


def test_state_machine_delete_then_recreate_same_path_invalidates(monkeypatch, tmp_path):
    """删除后恢复同路径：revision 递增保证旧确认失配。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    risky_step = db.get_step_by_name(workflow.id, "Step")
    db.delete_step(risky_step.id)
    # 重新创建同路径步骤
    db.create_step(workflow.id, "恢复", script_path="../outside.py")
    plan = _current_plan(db, workflow.id)
    assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
    assert evaluate_run_plan(plan) is None


def test_state_machine_copy_step_invalidates(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    step = db.get_steps_by_workflow(workflow.id)[0]
    db.copy_step(step.id)
    plan = _current_plan(db, workflow.id)
    assert compute_digest(plan.revision, plan.risk_records) != plan.confirmed_digest
    assert evaluate_run_plan(plan) is None


def test_state_machine_clone_retains_legacy_metadata_without_run_gate(monkeypatch, tmp_path):
    """克隆保留旧审核字段语义，但不再以此阻断运行。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    cloned = db.clone_workflow(workflow.id, "克隆副本")
    assert cloned is not None
    assert cloned.risky_paths_review_required == 1
    assert cloned.risky_paths_confirmed_digest is None
    assert evaluate_run_plan(_current_plan(db, cloned.id)) is None

    # 显式旧 API 仍可调用，不是运行前置条件。
    db.confirm_risky_paths(cloned.id)
    assert evaluate_run_plan(_current_plan(db, cloned.id)) is None


def test_state_machine_clone_non_risky_stays_clear(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("普通工作流")
    db.create_step(workflow.id, "A", script_path="scripts/run.py")
    cloned = db.clone_workflow(workflow.id, "普通副本")
    assert cloned.risky_paths_review_required == 0
    assert cloned.risky_paths_confirmed_digest is None
    assert evaluate_run_plan(_current_plan(db, cloned.id)) is None


def test_state_machine_import_ignores_json_internal_fields(monkeypatch, tmp_path):
    """JSON 中同名内部字段（risky_paths_*）永不采信。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    payload_path = tmp_path / "forged.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": "wf_forged_json",
                        "name": "伪造字段",
                        "risky_paths_review_required": 0,
                        "risky_paths_revision": 99,
                        "risky_paths_confirmed_digest": "faked-digest",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "Step",
                                "step_type": "python",
                                "script": "C:/untrusted.py",
                                "cwd": "safe",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert db.import_from_json(payload_path) == 1
    workflow = db.get_workflow_by_uid("wf_forged_json")
    assert workflow.risky_paths_review_required == 1
    assert workflow.risky_paths_confirmed_digest is None
    assert workflow.risky_paths_revision != 99


def test_risky_paths_not_in_update_workflow_whitelist(monkeypatch, tmp_path):
    from database_field_guards import WORKFLOW_UPDATE_FIELDS

    assert "risky_paths_review_required" not in WORKFLOW_UPDATE_FIELDS
    assert "risky_paths_revision" not in WORKFLOW_UPDATE_FIELDS
    assert "risky_paths_confirmed_digest" not in WORKFLOW_UPDATE_FIELDS

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("白名单")
    with pytest.raises(ValueError):
        db.update_workflow(workflow.id, risky_paths_review_required=0)


def test_state_machine_confirm_missing_workflow_returns_false(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    assert db.confirm_risky_paths(99999) is False


def test_scoped_confirmation_db_state_and_invalidation(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow, steps = _import_two_risky_steps(db, tmp_path)
    selected = steps[0]

    assert db.confirm_risky_paths(workflow.id, step_uids=[selected.uid]) is True
    confirmed = db.get_workflow_by_id(workflow.id)
    assert confirmed.risky_paths_review_required is True
    assert confirmed.risky_paths_confirmed_digest.startswith(
        risk_path_review.SCOPED_CONFIRMATION_PREFIX
    )
    all_steps = db.get_steps_by_workflow(workflow.id)
    assert evaluate_run_plan(build_run_plan(
        confirmed, all_steps, selected_steps=[all_steps[0]]
    )) is None
    assert evaluate_run_plan(build_run_plan(
        confirmed, all_steps, selected_steps=[all_steps[1]]
    )) is None

    db.update_step(selected.id, script_path="C:/changed.py")
    changed = db.get_workflow_by_id(workflow.id)
    all_steps = db.get_steps_by_workflow(workflow.id)
    assert changed.risky_paths_revision > confirmed.risky_paths_revision
    assert evaluate_run_plan(build_run_plan(
        changed, all_steps, selected_steps=[all_steps[0]]
    )) is None

    with pytest.raises(ValueError, match="未知步骤"):
        db.confirm_risky_paths(workflow.id, step_uids=["not-in-workflow"])
