# -*- coding: utf-8 -*-
"""R1: 导入风险路径确认机制测试。

覆盖：
- 纯函数：digest 稳定性 / 路径规范化（Windows 大小写折叠、UNC、.. 折叠）
- 迁移 v10：幂等 / instr 字面匹配 / 伪造 [已确认] 不信任 / 旧库端到端
- 状态机：导入→确认→增删改路径→失配阻断、同路径换字段、删除恢复同路径、
  克隆重新确认、copy_step 失效
- CLI run/retry 门禁、--confirm-risky-paths、非 TTY、TTY 交互（含 EOFError）
- _import_and_run.py run 与 --auto 同一门禁
- 引擎 RunPlan 快照（阻断/放行/失配）
- H4: RunPlan 物化执行拷贝（StepSnapshot/WorkflowView）；真实 _begin_run 提交后
  并发修改 DB，执行仍消费校验时的快照（TOCTOU 不落空）
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
from _schema_guard_utils import _use_temp_database
from risk_path_review import (
    RunPlan,
    build_run_plan,
    collect_risk_paths,
    compute_digest,
    evaluate_run_plan,
    format_risk_records,
    looks_risky_path,
    normalize_path,
)


# ============== 纯函数：normalize_path ==============

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


# ============== 纯函数：looks_risky_path ==============

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


# ============== 纯函数：collect_risk_paths ==============

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


# ============== 纯函数：compute_digest ==============

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


# ============== 纯函数：format_risk_records ==============

def test_format_risk_records_readable():
    records = [
        risk_path_review.RiskRecord("s1", "script_path", "../a.py"),
        risk_path_review.RiskRecord("s2", "cwd", "c:/jobs"),
    ]
    text = format_risk_records(records)
    assert "s1" in text and "脚本路径" in text and "../a.py" in text
    assert "s2" in text and "工作目录" in text and "c:/jobs" in text


# ============== 纯函数：evaluate_run_plan ==============

def _wf(**overrides):
    fields = {
        "id": 1,
        "risky_paths_review_required": False,
        "risky_paths_revision": 0,
        "risky_paths_confirmed_digest": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _risky_steps():
    return [SimpleNamespace(uid="s1", step_type="python", script_path="C:/x.py", cwd=None)]


def test_evaluate_run_plan_rules():
    # 记录为空 → 放行（即使 review_required=1）
    assert evaluate_run_plan(build_run_plan(_wf(risky_paths_review_required=True), [])) is None
    # review_required=1 且有风险路径 → 阻断
    blocked = evaluate_run_plan(build_run_plan(_wf(risky_paths_review_required=True), _risky_steps()))
    assert blocked is not None and "未经确认" in blocked
    # review_required=0 且 digest 空 → 非导入/旧记录 → 放行
    assert evaluate_run_plan(build_run_plan(_wf(), _risky_steps())) is None
    # 摘要失配 → 阻断
    records = collect_risk_paths(_risky_steps())
    plan = build_run_plan(
        _wf(risky_paths_revision=7, risky_paths_confirmed_digest=compute_digest(6, records)),
        _risky_steps(),
    )
    blocked = evaluate_run_plan(plan)
    assert blocked is not None and "已发生变化" in blocked
    # 摘要匹配 → 放行
    plan = build_run_plan(
        _wf(risky_paths_revision=7, risky_paths_confirmed_digest=compute_digest(7, records)),
        _risky_steps(),
    )
    assert evaluate_run_plan(plan) is None


def test_run_plan_frozen_and_has_risk_records():
    records = collect_risk_paths(_risky_steps())
    plan = RunPlan(workflow_id=1, review_required=True, revision=2, confirmed_digest="x", risk_records=tuple(records))
    assert plan.has_risk_records is True
    with pytest.raises(Exception):
        plan.risk_records = ()  # frozen dataclass 不可变
    assert RunPlan(1, False, 0, None, ()).has_risk_records is False


# ============== 迁移 v10 ==============

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


# ============== 迁移 v11 ==============

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


# ============== 状态机 ==============

def _import_risky_workflow(db, tmp_path, *, uid="wf_risky", name="风险路径工作流", script="../outside.py"):
    payload_path = tmp_path / f"{uid}.json"
    payload_path.write_text(
        json.dumps(
            {
                "version": 1,
                "workflows": [
                    {
                        "id": uid,
                        "name": name,
                        "description": "说明",
                        "steps": [
                            {
                                "id": "step_1",
                                "name": "Step",
                                "step_type": "python",
                                "script": script,
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
    return db.get_workflow_by_uid(uid)


def _current_plan(db, workflow_id):
    workflow = db.get_workflow_by_id(workflow_id)
    steps = db.get_steps_by_workflow(workflow_id)
    return build_run_plan(workflow, steps)


def test_state_machine_import_confirm_edit_invalidate(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)

    # 导入 → review_required=1、digest 空、description 未被改写
    assert workflow.risky_paths_review_required == 1
    assert workflow.risky_paths_confirmed_digest is None
    assert workflow.description == "说明"
    revision_after_import = workflow.risky_paths_revision
    assert revision_after_import >= 1
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is not None

    # 确认 → 专用事务：revision+1、digest 计算、review_required=0
    assert db.confirm_risky_paths(workflow.id) is True
    workflow = db.get_workflow_by_id(workflow.id)
    assert workflow.risky_paths_review_required == 0
    assert workflow.risky_paths_confirmed_digest is not None
    assert workflow.risky_paths_revision == revision_after_import + 1
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    # 修改 script_path → revision 递增 → 摘要失配 → 阻断
    step = db.get_steps_by_workflow(workflow.id)[0]
    db.update_step(step.id, script_path="C:/changed.py")
    workflow = db.get_workflow_by_id(workflow.id)
    assert workflow.risky_paths_revision == revision_after_import + 2
    blocked = evaluate_run_plan(_current_plan(db, workflow.id))
    assert blocked is not None and "已发生变化" in blocked


def test_state_machine_same_path_other_field_invalidates(monkeypatch, tmp_path):
    """同路径换字段（script_path → cwd）：确认摘要同样失配。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    step = db.get_steps_by_workflow(workflow.id)[0]
    db.update_step(step.id, cwd="C:/other-dir")
    blocked = evaluate_run_plan(_current_plan(db, workflow.id))
    assert blocked is not None and "已发生变化" in blocked


def test_state_machine_add_and_delete_step_invalidate(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    # 新增步骤（含风险路径）→ 失配
    db.create_step(workflow.id, "新增", script_path="D:/new.py")
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is not None

    # 重新确认后删除风险步骤 → 失配
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None
    risky_step = db.get_step_by_name(workflow.id, "Step")
    db.delete_step(risky_step.id)
    blocked = evaluate_run_plan(_current_plan(db, workflow.id))
    assert blocked is not None and "已发生变化" in blocked


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
    blocked = evaluate_run_plan(_current_plan(db, workflow.id))
    assert blocked is not None and "已发生变化" in blocked


def test_state_machine_copy_step_invalidates(monkeypatch, tmp_path):
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    step = db.get_steps_by_workflow(workflow.id)[0]
    db.copy_step(step.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is not None


def test_state_machine_clone_requires_reconfirm(monkeypatch, tmp_path):
    """克隆仍含风险路径 → 强制 review_required=1、digest 空（不继承原确认）。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    db.confirm_risky_paths(workflow.id)
    assert evaluate_run_plan(_current_plan(db, workflow.id)) is None

    cloned = db.clone_workflow(workflow.id, "克隆副本")
    assert cloned is not None
    assert cloned.risky_paths_review_required == 1
    assert cloned.risky_paths_confirmed_digest is None
    assert evaluate_run_plan(_current_plan(db, cloned.id)) is not None

    # 确认后克隆放行
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


# ============== 引擎 RunPlan 快照 ==============

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

    monkeypatch.setattr("engine.LOG_DIR", tmp_path)
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


def test_engine_run_blocked_when_review_required(monkeypatch, tmp_path):
    from engine import RunMode, WorkflowEngine

    engine = WorkflowEngine()
    try:
        workflow = SimpleNamespace(
            id=1, uid="wf-1", name="主工作流", log_retention_days=1,
            single_script_enabled=False, parallel_enabled=False,
            get_notify_config=lambda: {},
            risky_paths_review_required=1, risky_paths_revision=1,
            risky_paths_confirmed_digest=None,
        )
        steps = [SimpleNamespace(
            id=1, uid="step-a", order=1, name="A",
            step_type="python", script_path="C:/evil.py", cwd=None,
        )]
        logs = []
        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 1 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: steps if workflow_id == 1 else [])
        monkeypatch.setattr(engine, "_emit_log", lambda message: logs.append(message))
        monkeypatch.setattr(engine, "_execute_steps", lambda *a, **k: pytest.fail("不应执行步骤"))

        ok = engine.run(1, RunMode.FULL)
        assert ok is False
        assert any("未经确认" in message for message in logs)
    finally:
        engine.shutdown(wait=False)


def test_engine_run_blocked_on_digest_mismatch(monkeypatch, tmp_path):
    from engine import RunMode, WorkflowEngine

    engine = WorkflowEngine()
    try:
        steps = [SimpleNamespace(
            id=1, uid="step-a", order=1, name="A",
            step_type="python", script_path="C:/evil.py", cwd=None,
        )]
        records = collect_risk_paths(steps)
        workflow = SimpleNamespace(
            id=1, uid="wf-1", name="主工作流", log_retention_days=1,
            single_script_enabled=False, parallel_enabled=False,
            get_notify_config=lambda: {},
            risky_paths_review_required=0, risky_paths_revision=9,
            risky_paths_confirmed_digest=compute_digest(8, records),  # revision 失配
        )
        logs = []
        monkeypatch.setattr("engine.LOG_DIR", tmp_path)
        monkeypatch.setattr("engine.get_workflow_by_id", lambda workflow_id: workflow if workflow_id == 1 else None)
        monkeypatch.setattr("engine.get_steps_by_workflow", lambda workflow_id: steps if workflow_id == 1 else [])
        monkeypatch.setattr(engine, "_emit_log", lambda message: logs.append(message))
        monkeypatch.setattr(engine, "_execute_steps", lambda *a, **k: pytest.fail("不应执行步骤"))

        ok = engine.run(1, RunMode.FULL)
        assert ok is False
        assert any("已发生变化" in message for message in logs)
    finally:
        engine.shutdown(wait=False)


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

    校验通过后（spy 在 _begin_run 的 update_run_history 提交后调用 update_step）
    并发修改 script_path，执行收到的仍是 plan 快照旧值（StepSnapshot）；
    DB 中已是新路径，且重新校验需确认（revision 递增 → digest 失配）。
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

        # DB 中已是并发修改后的新路径；重新校验需确认
        assert db.get_steps_by_workflow(workflow_id)[0].script_path == "C:/changed.py"
        blocked = evaluate_run_plan(_current_plan(db, workflow_id))
        assert blocked is not None and "已发生变化" in blocked
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


# ============== CLI 门禁（进程内：TTY 交互 / EOFError） ==============

def _make_cli_risky_env(monkeypatch, tmp_path):
    """返回 (db, workflow_id)；cli 模块惰性引用 database 全局，随 monkeypatch 生效。"""
    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = _import_risky_workflow(db, tmp_path)
    return db, workflow.id


def test_cli_gate_tty_interactive_yes_and_no(monkeypatch, tmp_path):
    from cli import _confirm_risky_paths

    db, workflow_id = _make_cli_risky_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))

    answers = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    # n → 拒绝
    assert _confirm_risky_paths(workflow_id, auto_confirm=False) is False
    workflow = db.get_workflow_by_id(workflow_id)
    assert workflow.risky_paths_review_required == 1

    # y → 确认并放行
    assert _confirm_risky_paths(workflow_id, auto_confirm=False) is True
    workflow = db.get_workflow_by_id(workflow_id)
    assert workflow.risky_paths_review_required == 0
    assert workflow.risky_paths_confirmed_digest is not None
    # 已确认 → 直接放行
    assert _confirm_risky_paths(workflow_id, auto_confirm=False) is True


def test_cli_gate_tty_eof_error_treated_as_reject(monkeypatch, tmp_path):
    from cli import _confirm_risky_paths

    db, workflow_id = _make_cli_risky_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(EOFError))

    assert _confirm_risky_paths(workflow_id, auto_confirm=False) is False
    workflow = db.get_workflow_by_id(workflow_id)
    assert workflow.risky_paths_review_required == 1


def test_cli_gate_non_tty_requires_flag(monkeypatch, tmp_path):
    from cli import _confirm_risky_paths

    db, workflow_id = _make_cli_risky_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))

    assert _confirm_risky_paths(workflow_id, auto_confirm=False) is False
    workflow = db.get_workflow_by_id(workflow_id)
    assert workflow.risky_paths_review_required == 1

    assert _confirm_risky_paths(workflow_id, auto_confirm=True) is True
    workflow = db.get_workflow_by_id(workflow_id)
    assert workflow.risky_paths_review_required == 0


def test_cli_gate_clear_workflow_passes_without_dialog(monkeypatch, tmp_path):
    from cli import _confirm_risky_paths

    db = _use_temp_database(monkeypatch, tmp_path)
    workflow = db.create_workflow("普通")
    db.create_step(workflow.id, "A", script_path="scripts/run.py")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert _confirm_risky_paths(workflow.id, auto_confirm=False) is True


# ============== CLI 子进程（非 TTY 端到端） ==============

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


def test_cli_run_risky_blocked_non_tty_without_flag(tmp_path):
    app_data_dir = tmp_path / "cli-run-app-data"
    payload = _write_risky_payload(tmp_path)
    workflow_id = _seed_import_and_get_id(app_data_dir, payload, "CLI风险工作流")

    result = _run_python(app_data_dir, CLI_SCRIPT, "run", str(workflow_id))

    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "未经确认的风险路径" in output
    assert "--confirm-risky-paths" in output
    assert "非交互环境请显式使用" in output


def test_cli_run_risky_auto_confirmed_with_flag_succeeds(tmp_path):
    app_data_dir = tmp_path / "cli-run-flag-app-data"
    payload = _write_risky_payload(tmp_path)
    workflow_id = _seed_import_and_get_id(app_data_dir, payload, "CLI风险工作流")

    result = _run_python(app_data_dir, CLI_SCRIPT, "run", str(workflow_id), "--confirm-risky-paths")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "工作流结束" in output
    assert "成功" in output


def test_cli_retry_risky_blocked_non_tty_without_flag(tmp_path):
    app_data_dir = tmp_path / "cli-retry-app-data"
    payload = _write_risky_payload(tmp_path)
    workflow_id = _seed_import_and_get_id(app_data_dir, payload, "CLI风险工作流")

    result = _run_python(app_data_dir, CLI_SCRIPT, "retry", str(workflow_id))

    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "未经确认的风险路径" in output
    assert "--confirm-risky-paths" in output


# ============== _import_and_run.py 门禁（run 与 --auto 同一门禁） ==============

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


def test_import_and_run_run_requires_flag(tmp_path):
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
    assert result.returncode == 1, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "未经确认的风险路径" in output
    assert "--confirm-risky-paths" in output


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
