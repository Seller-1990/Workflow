# -*- coding: utf-8 -*-
"""数据库连接与 CRUD 操作"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Generator

from sqlalchemy import create_engine, event, text, func
from sqlalchemy.orm import sessionmaker, Session, joinedload, scoped_session

from config import DATABASE_PATH
from database_backup import auto_backup_workflows_impl
from database_clone import clone_workflow_impl
from database_field_guards import (
    RUN_HISTORY_UPDATE_FIELDS,
    STAGE_UPDATE_FIELDS,
    STEP_LOG_UPDATE_FIELDS,
    STEP_UPDATE_FIELDS,
    WEBHOOK_UPDATE_FIELDS,
    WORKFLOW_UPDATE_FIELDS,
    validate_update_fields as _validate_update_fields,
)
from database_migration_backup import create_migration_snapshot
from database_import_export import (
    ImportResult,
    export_to_json_impl,
    import_from_json_impl,
)
from webhook_url_policy import (
    is_masked_webhook_url as _is_masked_webhook_url,
    is_valid_dingtalk_webhook_url,
)
from models import Base, Workflow, WorkflowStage, Step, RunHistory, StepLog, RecentWorkflow, WebhookConfig

import risk_path_review

logger = logging.getLogger(__name__)

MASKED_WEBHOOK_URL = "__WORKFLOW_WEBHOOK_URL_MASKED__"


# 循环依赖检测缓存（模块级）
# L2: 使用工作流 updated_at 作为缓存 key 的一部分，避免在 60s 窗口内编辑工作流后命中陈旧缓存
_cycle_check_cache = {}
_cycle_check_cache_time = 0.0
_cycle_check_cache_lock = threading.Lock()


def invalidate_cycle_check_cache() -> None:
    """L2: 工作流结构变更时由调用方主动失效，避免缓存陈旧"""
    global _cycle_check_cache, _cycle_check_cache_time
    with _cycle_check_cache_lock:
        _cycle_check_cache = {}
        _cycle_check_cache_time = 0.0


# 创建数据库引擎
def get_engine():
    """获取数据库引擎"""
    engine = create_engine(
        f"sqlite:///{DATABASE_PATH}",
        echo=False,
        connect_args={"check_same_thread": False}
    )
    
    # 启用外键约束和 WAL 模式
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")  # 增加到 10 秒，减少写锁竞争
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    
    return engine


# 全局引擎和会话工厂
_engine = None
_SessionFactory = None
_scoped_session = None
_init_lock = threading.RLock()  # R9-#1: 必须 RLock——init_db 持锁时会调 _ensure_stage_data → get_session 再次 acquire
_init_done = False  # P-16: 进程内幂等：多次 init_db 只跑一次


def _max_applied_version(engine) -> int:
    """R2-#6: 读取 schema_versions 中已应用的最大版本号；表/数据不存在返回 0"""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT MAX(version) FROM schema_versions")).fetchone()
            if not row or row[0] is None:
                return 0
            return int(row[0])
    except Exception:
        return 0


def init_db():
    """初始化数据库（进程内幂等）

    迁移检查直接以库内 schema_versions MAX(version) 为准（F-02：不依赖任何
    外部缓存文件——缓存与 DB 脱钩会导致还原旧库后迁移被跳过）。
    每次启动多付一次小表 SELECT + PRAGMA 探测，成本可忽略。
    """
    global _engine, _SessionFactory, _scoped_session, _init_done

    with _init_lock:
        # P-16: 同进程内 init_db 多次调用直接返回
        if _init_done and _engine is not None:
            return _engine

        _engine = get_engine()
        # F-01: expire_on_commit=False——commit 不再过期线程 identity map 中的
        # ORM 对象，get_session 退出时统一 close（连接归还池、identity map 清空），
        # 返回对象为 detached 且列属性已加载。据此删除 H4 re-fetch / fallback
        # 复制对象 / PF2 expire 循环等复杂度补偿（同一改动集）。
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
        # 使用scoped_session支持多线程安全
        _scoped_session = scoped_session(_SessionFactory)

        # 创建所有表（IF NOT EXISTS，已存在时仅做轻量 PRAGMA）
        Base.metadata.create_all(_engine)

        _ensure_schema_version_table(_engine)
        # HA2 修复：用 schema_version 跳过已完成的迁移，避免每次启动重跑 PRAGMA table_info + ALTER
        _run_pending_migrations(_engine)

        _ensure_stage_data()
        _init_done = True

        return _engine


# ============== Schema 版本控制 ==============
# 新增迁移必须 (1) 注册到 SCHEMA_MIGRATIONS，(2) 写一个回调函数完成具体改动。
# 已执行的版本会被记录在 schema_versions 表中，不会重复执行。
SCHEMA_MIGRATIONS: list[tuple[int, str]] = [
    (1, "_migrate_v1_workflow_step_runhistory_columns"),
    (2, "_migrate_v2_version_table_and_step_uid_unique"),
    (3, "_migrate_v3_step_logs_step_run_index"),
    (4, "_migrate_v4_workflow_version_unique"),
    (5, "_migrate_v5_webhook_name_unique"),
    (6, "_migrate_v6_run_history_notify_status"),
    (7, "_migrate_v7_step_output_paths"),
    (8, "_migrate_v8_run_history_step_log_perf_indexes"),
    (9, "_migrate_v9_step_saved_run_args"),
    (10, "_migrate_v10_risky_paths_review"),
    (11, "_migrate_v11_clamp_workflow_max_workers"),
]


def _ensure_schema_version_table(engine):
    """创建版本号记录表"""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_versions ("
            "version INTEGER PRIMARY KEY,"
            "applied_at DATETIME DEFAULT CURRENT_TIMESTAMP"
            ")"
        ))


def _get_applied_versions(engine) -> set[int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_versions")).fetchall()
        return {int(r[0]) for r in rows}


def _record_version(engine, version: int):
    with engine.begin() as conn:
        conn.execute(text("INSERT OR IGNORE INTO schema_versions(version) VALUES (:v)"), {"v": version})


def _run_pending_migrations(engine):
    """按 SCHEMA_MIGRATIONS 顺序运行未应用的迁移。"""
    applied = _get_applied_versions(engine)
    pending = [(version, name) for version, name in SCHEMA_MIGRATIONS if version not in applied]
    if pending:
        target_version = max(version for version, _ in pending)
        snapshot_path = create_migration_snapshot(Path(DATABASE_PATH), target_version)
        logger.info("schema 迁移前快照已创建: %s", snapshot_path)
    for version, func_name in pending:
        if version in applied:
            continue
        func = globals().get(func_name)
        if not callable(func):
            raise RuntimeError(f"schema 迁移函数 {func_name} 未定义，无法升级到版本 {version}")
        try:
            func(engine)
            _record_version(engine, version)
            logger.info("schema 迁移完成: v%s (%s)", version, func_name)
        except Exception as e:
            logger.exception("schema 迁移 v%s 失败: %s", version, e)
            raise RuntimeError(f"schema 迁移 v{version} 失败，应用已停止启动以避免写入半升级数据库") from e


def _migrate_v1_workflow_step_runhistory_columns(engine):
    """v1: 补齐 workflow / step / run_history 早期版本未包含的列"""
    _ensure_workflow_columns(engine)
    _ensure_step_columns(engine)
    _ensure_run_history_columns(engine)


def _migrate_v6_run_history_notify_status(engine):
    """v6 (ROI-1): run_histories 增加 notify_status 列（通知结果回写）。

    新建库由 Base.metadata.create_all 直接带列；老库按 PRAGMA 探测后 ALTER，
    两种路径都安全幂等。
    """
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(run_histories)")).fetchall()
        existing = {row[1] for row in rows}
        if "notify_status" not in existing:
            conn.execute(text("ALTER TABLE run_histories ADD COLUMN notify_status VARCHAR(255)"))


def _migrate_v7_step_output_paths(engine):
    """v7 (ROI-2): steps 增加 output_paths 列（显式输出声明，JSON 数组）。"""
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(steps)")).fetchall()
        existing = {row[1] for row in rows}
        if "output_paths" not in existing:
            conn.execute(text("ALTER TABLE steps ADD COLUMN output_paths TEXT"))


def _migrate_v8_run_history_step_log_perf_indexes(engine):
    """v8 (P-17): 为运行历史列表和步骤日志详情查询补充组合索引。"""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_run_histories_wf_start_id "
            "ON run_histories(workflow_id, start_time, id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_step_logs_run_order "
            "ON step_logs(run_history_id, \"order\")"
        ))


def _migrate_v9_step_saved_run_args(engine):
    """v9: steps 增加 saved_run_args 列（可持久化的运行参数默认层）。"""
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(steps)")).fetchall()
        existing = {row[1] for row in rows}
        if "saved_run_args" not in existing:
            conn.execute(text("ALTER TABLE steps ADD COLUMN saved_run_args TEXT"))


# 旧版文本标记（v10 迁移只读取它来回填，运行判定不再使用）
_LEGACY_IMPORTED_PATH_WARNING = "[导入提示]"


def _migrate_v10_risky_paths_review(engine):
    """v10 (R1): workflows 增加风险路径确认三列，并按旧文本标记回填。

    迁移规则：
    1. 旧记录默认不建立信任（review_required=0、digest NULL —— 运行判定放行）。
    2. description 含旧 `[导入提示]` 字面标记的记录置 review_required=1、digest 空
       （用 instr 精确匹配字面量，不用 LIKE 防 `[...]` 字符类假阳性）。
    3. 即使 description 含 `[已确认]` 也不 backfill 信任（description 是用户可控输入）。
    4. 旧文本不再参与运行判定（运行时只读三列）。

    幂等：列存在则跳过 ALTER；UPDATE 重复执行无副作用。
    """
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(workflows)")).fetchall()
        existing = {row[1] for row in rows}
        if "risky_paths_review_required" not in existing:
            conn.execute(text(
                "ALTER TABLE workflows ADD COLUMN "
                "risky_paths_review_required INTEGER NOT NULL DEFAULT 0"
            ))
        if "risky_paths_revision" not in existing:
            conn.execute(text(
                "ALTER TABLE workflows ADD COLUMN "
                "risky_paths_revision INTEGER NOT NULL DEFAULT 0"
            ))
        if "risky_paths_confirmed_digest" not in existing:
            conn.execute(text(
                "ALTER TABLE workflows ADD COLUMN "
                "risky_paths_confirmed_digest TEXT"
            ))
        conn.execute(text(
            "UPDATE workflows SET "
            "risky_paths_review_required = 1, "
            "risky_paths_confirmed_digest = NULL "
            "WHERE description IS NOT NULL "
            "AND instr(description, :marker) > 0"
        ), {"marker": _LEGACY_IMPORTED_PATH_WARNING})


def _migrate_v11_clamp_workflow_max_workers(engine):
    """v11 (R5): 旧库 max_workers 越界值(<1 或 >8)归一到边界并记录数量(幂等)。

    资源保护而非死锁证明:执行期另有夹紧兜底;此处只在升级时归一历史数据。
    max_workers 列由 ORM create_all 建表提供,手工构造的旧表可能没有该列,
    探测缺失时跳过(该列不存在即无需归一)。
    """
    from constants import WORKFLOW_MAX_WORKERS_MIN, WORKFLOW_MAX_WORKERS_MAX
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(workflows)")).fetchall()}
        if "max_workers" not in columns:
            return
        low = conn.execute(text(
            "SELECT COUNT(*) FROM workflows WHERE max_workers < :min"
        ), {"min": WORKFLOW_MAX_WORKERS_MIN}).scalar()
        high = conn.execute(text(
            "SELECT COUNT(*) FROM workflows WHERE max_workers > :max"
        ), {"max": WORKFLOW_MAX_WORKERS_MAX}).scalar()
        if low:
            conn.execute(text(
                "UPDATE workflows SET max_workers=:min WHERE max_workers < :min"
            ), {"min": WORKFLOW_MAX_WORKERS_MIN})
        if high:
            conn.execute(text(
                "UPDATE workflows SET max_workers=:max WHERE max_workers > :max"
            ), {"max": WORKFLOW_MAX_WORKERS_MAX})
        if low or high:
            logger.warning(
                "v11 迁移: 归一化 max_workers 越界值 %d 个(<1) / %d 个(>8)",
                low, high,
            )


def _migrate_v2_version_table_and_step_uid_unique(engine):
    """v2: 工作流版本表 + step (workflow_id, uid) 唯一索引"""
    _ensure_version_table(engine)
    _ensure_step_uid_unique(engine)


def _migrate_v3_step_logs_step_run_index(engine):
    """v3: R2-#5 为 step_logs 加 (step_id, run_history_id) 组合索引"""
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_step_logs_step_run "
                "ON step_logs(step_id, run_history_id)"
            ))
        except Exception as e:
            logger.warning("创建 ix_step_logs_step_run 失败: %s", e)


def _migrate_v4_workflow_version_unique(engine):
    """v4: 为 workflow_versions 建立 (workflow_id, version) 唯一约束。"""
    _ensure_version_table(engine)
    _ensure_workflow_version_unique(engine)


def _migrate_v5_webhook_name_unique(engine):
    """v5: 清理重复 webhook 名称后建立唯一索引。"""
    _ensure_webhook_name_unique(engine)


def _ensure_workflow_columns(engine):
    """兼容老库：补齐新增字段"""
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(workflows)")).fetchall()
        existing = {row[1] for row in rows}
        alter_sql = []
        if "watch_enabled" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN watch_enabled INTEGER DEFAULT 0")
        if "watch_mode" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN watch_mode VARCHAR(64) DEFAULT 'any_change'")
        if "watch_folders" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN watch_folders TEXT")
        if "cooldown_seconds" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN cooldown_seconds INTEGER DEFAULT 8")
        if "settle_seconds" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN settle_seconds INTEGER DEFAULT 15")
        if "single_script_enabled" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN single_script_enabled INTEGER DEFAULT 0")
        if "single_script_type" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN single_script_type VARCHAR(32) DEFAULT 'python'")
        if "single_script_path" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN single_script_path TEXT")
        if "single_script_args" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN single_script_args TEXT")
        if "single_script_cwd" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN single_script_cwd TEXT")
        if "log_retention_days" not in existing:
            alter_sql.append("ALTER TABLE workflows ADD COLUMN log_retention_days INTEGER DEFAULT 30")
        for sql in alter_sql:
            conn.execute(text(sql))


def _ensure_version_table(engine):
    """兼容老库：创建工作流版本表"""
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS workflow_versions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "workflow_id INTEGER NOT NULL,"
            "version INTEGER NOT NULL,"
            "snapshot TEXT NOT NULL,"
            "change_reason VARCHAR(255),"
            "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
            "FOREIGN KEY(workflow_id) REFERENCES workflows(id)"
            ")"
        ))
        # 创建索引（如果不存在不报错）
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wf_versions_wf_id ON workflow_versions(workflow_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_wf_versions_created ON workflow_versions(created_at)"))
        except Exception:
            pass


def _ensure_workflow_version_unique(engine):
    """清理重复版本号后建立 workflow_versions 唯一索引。"""
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, workflow_id, version FROM workflow_versions "
            "ORDER BY workflow_id, version, created_at, id"
        )).fetchall()
        by_workflow: dict[int, list[tuple[int, int]]] = {}
        for row_id, workflow_id, version in rows:
            by_workflow.setdefault(int(workflow_id), []).append((int(row_id), int(version)))

        for workflow_id, versions in by_workflow.items():
            used: set[int] = set()
            next_version = max((version for _, version in versions), default=0) + 1
            for row_id, version in versions:
                if version not in used:
                    used.add(version)
                    continue
                while next_version in used:
                    next_version += 1
                conn.execute(
                    text("UPDATE workflow_versions SET version=:version WHERE id=:id"),
                    {"version": next_version, "id": row_id},
                )
                used.add(next_version)
                logger.warning(
                    "已修正重复工作流版本号: workflow_id=%s, row_id=%s, new_version=%s",
                    workflow_id,
                    row_id,
                    next_version,
                )
                next_version += 1

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_versions_workflow_version "
            "ON workflow_versions(workflow_id, version)"
        ))


def _ensure_webhook_name_unique(engine):
    """清理重复 webhook 名称后建立唯一索引。"""
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, name FROM webhook_configs "
            "ORDER BY name, id"
        )).fetchall()

        keep_by_name: dict[str, int] = {}
        duplicate_to_keep: dict[int, int] = {}
        duplicate_ids: list[int] = []

        for row_id, name in rows:
            normalized_name = str(name or "")
            existing_id = keep_by_name.get(normalized_name)
            if existing_id is None:
                keep_by_name[normalized_name] = int(row_id)
                continue
            duplicate_id = int(row_id)
            duplicate_to_keep[duplicate_id] = existing_id
            duplicate_ids.append(duplicate_id)
            logger.warning(
                "已修正重复 webhook 名称: name=%r, keep_id=%s, drop_id=%s",
                normalized_name,
                existing_id,
                duplicate_id,
            )

        if duplicate_to_keep:
            workflows = conn.execute(text(
                "SELECT id, notify_config FROM workflows "
                "WHERE notify_config IS NOT NULL AND notify_config != ''"
            )).fetchall()
            for workflow_id, notify_config in workflows:
                try:
                    notify = json.loads(notify_config)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(notify, dict):
                    continue

                webhook_id = notify.get("webhook_id")
                if isinstance(webhook_id, str):
                    if not webhook_id.isdigit():
                        continue
                    webhook_id = int(webhook_id)
                if not isinstance(webhook_id, int):
                    continue
                if webhook_id not in duplicate_to_keep:
                    continue

                notify["webhook_id"] = duplicate_to_keep[webhook_id]
                conn.execute(
                    text("UPDATE workflows SET notify_config=:notify_config WHERE id=:id"),
                    {
                        "notify_config": json.dumps(notify, ensure_ascii=False),
                        "id": workflow_id,
                    },
                )

            for duplicate_id in duplicate_ids:
                conn.execute(
                    text("DELETE FROM webhook_configs WHERE id=:id"),
                    {"id": duplicate_id},
                )

        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_webhook_configs_name "
            "ON webhook_configs(name)"
        ))


def _ensure_run_history_columns(engine):
    """兼容老库：补齐运行历史新增字段（trace_id, parent_run_id）"""
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(run_histories)")).fetchall()
        existing = {row[1] for row in rows}
        alter_sql = []
        if "trace_id" not in existing:
            alter_sql.append("ALTER TABLE run_histories ADD COLUMN trace_id VARCHAR(64)")
        if "parent_run_id" not in existing:
            alter_sql.append("ALTER TABLE run_histories ADD COLUMN parent_run_id VARCHAR(64)")
        for sql in alter_sql:
            conn.execute(text(sql))


def _ensure_step_columns(engine):
    """兼容老库：补齐 steps 表新增字段"""
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(steps)")).fetchall()
        existing = {row[1] for row in rows}
        alter_sql = []
        if "skip_on_success" not in existing:
            alter_sql.append("ALTER TABLE steps ADD COLUMN skip_on_success INTEGER DEFAULT 0")
        if "stage_uid" not in existing:
            alter_sql.append("ALTER TABLE steps ADD COLUMN stage_uid VARCHAR(64)")
        for sql in alter_sql:
            conn.execute(text(sql))


def _ensure_step_uid_unique(engine):
    """H10 修复：清除 (workflow_id, uid) 重复后建立 unique index

    场景：import_from_json 或 ensure_single_script_step 在历史上可能在同一 workflow
    下产生重复 uid（特别是 uid='single_script'）。清重保留 id 最大者（最新）。
    """
    with engine.begin() as conn:
        # 1) 探测重复
        dup_rows = conn.execute(text(
            "SELECT workflow_id, uid, COUNT(*) c FROM steps "
            "GROUP BY workflow_id, uid HAVING c > 1"
        )).fetchall()
        for wf_id, uid, _ in dup_rows:
            # 保留最新（id 最大），删除其余
            keep_id = conn.execute(text(
                "SELECT MAX(id) FROM steps WHERE workflow_id=:w AND uid=:u"
            ), {"w": wf_id, "u": uid}).scalar()
            conn.execute(text(
                "UPDATE step_logs SET step_id=:k "
                "WHERE step_id IN ("
                "SELECT id FROM steps WHERE workflow_id=:w AND uid=:u AND id != :k"
                ")"
            ), {"w": wf_id, "u": uid, "k": keep_id})
            conn.execute(text(
                "DELETE FROM steps WHERE workflow_id=:w AND uid=:u AND id != :k"
            ), {"w": wf_id, "u": uid, "k": keep_id})
        # 2) 创建 unique index（IF NOT EXISTS 幂等）；失败必须中止迁移，避免版本已记录但约束缺失。
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_steps_workflow_uid "
            "ON steps(workflow_id, uid)"
        ))


def _ensure_default_stage_in_session(session: Session, workflow_id: int) -> WorkflowStage:
    """确保工作流至少有一个用途阶段（默认阶段）"""
    stage = (
        session.query(WorkflowStage)
        .filter(WorkflowStage.workflow_id == workflow_id)
        .order_by(WorkflowStage.created_at.asc(), WorkflowStage.id.asc())
        .first()
    )
    if stage:
        return stage
    stage = WorkflowStage(
        uid=generate_uid(),
        workflow_id=workflow_id,
        name="默认阶段",
        order=0,
        color=None,
    )
    session.add(stage)
    session.flush()
    return stage


def _ensure_stage_data():
    """兼容老库：为缺少默认阶段的工作流补齐默认阶段，并为旧步骤填充 stage_uid"""
    with get_session() as session:
        workflows_without_stage = session.query(Workflow.id).outerjoin(
            WorkflowStage, Workflow.id == WorkflowStage.workflow_id
        ).filter(WorkflowStage.id.is_(None)).all()
        for (wf_id,) in workflows_without_stage:
            _ensure_default_stage_in_session(session, wf_id)
        # 为旧步骤填充缺失的 stage_uid
        session.query(Step).filter(
            Step.stage_uid.is_(None),
        ).update({Step.stage_uid: ""}, synchronize_session=False)
        session.commit()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """获取数据库会话（上下文管理器）- 线程安全

    F-01 修复后的契约：
    - ``expire_on_commit=False``（见 init_db）：commit 不再使已加载 ORM 对象过期，
      H4 re-fetch / fallback 复制 / 快照物化等复杂度补偿不再需要。
    - with 块退出时 ``close()`` 当前线程的 session（不 ``remove()`` 整个注册表）：
      连接归还池、identity map 清空，返回的对象成为 detached（列属性已加载可读）。
      约束 1：调用方不得在块外访问 relationship（当前全库审计仅在块内访问，
      database_clone.py / database_import_export.py 均在 session 存活期消费）。
      约束 2：本上下文不可嵌套使用（同线程 scoped_session 复用同一 session，
      内层 close 会影响外层）；AST 全库审计确认当前无嵌套调用点。
    - 异常路径仍 ``remove()``，丢弃受污染的 session。

    嵌套注意：同线程嵌套调用 get_session 时，内层 close 会一并关闭外层仍在
    使用的 session（scoped_session 复用同一线程 session）——AST 全库审计确认
    当前无嵌套调用点，此为隐性契约而非运行时强制检测。
    """
    global _scoped_session

    with _init_lock:
        if _scoped_session is None:
            init_db()

    session = _scoped_session()
    try:
        yield session
    except Exception:
        session.rollback()
        # 异常路径：丢弃当前线程的 session，避免后续调用使用受污染的状态
        try:
            _scoped_session.remove()
        except Exception:
            pass
        raise
    else:
        session.close()


def cleanup_session():
    """应用退出 / 工作线程结束时显式释放当前线程的 session

    用于避免长跑后 identity map 与连接累积。在 ThreadPoolExecutor 的 worker
    线程结束、或主应用 closeEvent 中调用即可。
    """
    global _scoped_session
    if _scoped_session is None:
        return
    try:
        _scoped_session.remove()
    except Exception:
        pass


def generate_uid() -> str:
    """生成唯一 ID"""
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


# ============== R1: 导入风险路径确认机制 ==============

@event.listens_for(Session, "before_flush")
def _before_flush_bump_risky_paths_revision(session, flush_context, instances):
    """R1: 所有 Step 写路径在同一事务内递增所属工作流 risky_paths_revision。

    覆盖 create / copy / import / clone / delete / script_path、cwd 变更，
    使既有确认 digest 失效（删除后恢复同路径也不得沿用旧确认）。
    递增失败只记日志不阻断写入（避免把普通写路径变成高危操作）。
    """
    try:
        _bump_risky_paths_revision(session)
    except Exception:
        logger.exception("R1: 风险路径 revision 递增失败")


def _step_path_fields_changed(step) -> bool:
    """dirty 步骤是否发生 script_path / cwd 变更。"""
    from sqlalchemy import inspect as _orm_inspect

    state = _orm_inspect(step)
    for field in ("script_path", "cwd"):
        try:
            attr = state.attrs[field]
        except KeyError:
            continue
        if attr.history.has_changes():
            return True
    return False


def _bump_risky_paths_revision(session) -> None:
    """收集本次 flush 中受 Step 写路径影响的工作流 ID 并递增 revision。"""
    if not (session.new or session.dirty or session.deleted):
        return
    touched: set[int] = set()
    for step in session.new:
        if isinstance(step, Step) and step.workflow_id:
            touched.add(step.workflow_id)
    for step in session.deleted:
        if isinstance(step, Step) and step.workflow_id:
            touched.add(step.workflow_id)
    for step in session.dirty:
        if isinstance(step, Step) and step.workflow_id and _step_path_fields_changed(step):
            touched.add(step.workflow_id)
    for workflow_id in touched:
        workflow = session.get(Workflow, workflow_id)
        if workflow is None:
            continue
        workflow.risky_paths_revision = int(workflow.risky_paths_revision or 0) + 1


def confirm_risky_paths(workflow_id: int) -> bool:
    """R1: 用户确认导入风险路径安全（专用事务 API）。

    同一事务内重读当前路径 → revision+1 → compute_digest → review_required=0。
    之后任何 Step 写路径都会递增 revision 使本确认失效。
    """
    with get_session() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow is None:
            return False
        steps = session.query(Step).filter(Step.workflow_id == workflow_id).all()
        records = risk_path_review.collect_risk_paths(steps)
        workflow.risky_paths_revision = int(workflow.risky_paths_revision or 0) + 1
        workflow.risky_paths_confirmed_digest = risk_path_review.compute_digest(
            workflow.risky_paths_revision, records
        )
        workflow.risky_paths_review_required = 0
        session.commit()
        return True


def _reset_risky_review_after_clone(workflow_id: int) -> None:
    """R1: 克隆仍含风险路径 → 强制 review_required=1、digest 空（包装层二次事务）。

    不继承原工作流的确认状态；克隆成功后单独事务落库。
    """
    with get_session() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow is None:
            return
        steps = session.query(Step).filter(Step.workflow_id == workflow_id).all()
        if risk_path_review.collect_risk_paths(steps):
            workflow.risky_paths_review_required = 1
            workflow.risky_paths_confirmed_digest = None
            session.commit()


# ============== 跨工作流循环依赖检测 ==============

def has_cross_workflow_cycle(parent_id: int, target_uid: str) -> bool:
    """检测跨工作流循环依赖

    L2 修复：缓存 key 包含 (parent.updated_at, target.updated_at)，
    工作流结构变更后会自动失效；同时保留 60 秒上限作为兜底。
    """
    global _cycle_check_cache, _cycle_check_cache_time

    current_time = time.time()

    # 取两个工作流的 updated_at 作为版本指纹（任一变更则缓存失效）
    parent_ver = None
    target_ver = None
    try:
        with get_session() as session:
            row = session.query(Workflow.updated_at).filter(Workflow.id == parent_id).first()
            parent_ver = row[0].timestamp() if row and row[0] else None
            row = session.query(Workflow.updated_at).filter(Workflow.uid == target_uid).first()
            target_ver = row[0].timestamp() if row and row[0] else None
    except Exception:
        # 取版本失败：退化为不缓存（直接走实测路径）
        return _has_cross_workflow_cycle_impl(parent_id, target_uid)

    cache_key = (parent_id, target_uid, parent_ver, target_ver)

    with _cycle_check_cache_lock:
        # 兜底 TTL：60 秒
        if current_time - _cycle_check_cache_time > 60:
            _cycle_check_cache = {}
            _cycle_check_cache_time = current_time

        if cache_key in _cycle_check_cache:
            return _cycle_check_cache[cache_key]

    # 执行实际检测
    result = _has_cross_workflow_cycle_impl(parent_id, target_uid)

    with _cycle_check_cache_lock:
        _cycle_check_cache[cache_key] = result

    return result


def _has_cross_workflow_cycle_impl(parent_id: int, target_uid: str) -> bool:
    """检测跨工作流循环依赖的实际实现"""
    workflows = list_workflows()
    uid_to_id = {w.uid: w.id for w in workflows}
    target_id = uid_to_id.get(target_uid)
    if target_id is None:
        return False
    if target_id == parent_id:
        return True
    graph = {w.id: set() for w in workflows}
    # 一次查询获取所有子工作流步骤
    with get_session() as session:
        sub_steps = session.query(Step.step_type, Step.script_path, Step.workflow_id).filter(
            Step.step_type == "sub_workflow",
            Step.script_path.isnot(None)
        ).all()
    for st, sp, wid in sub_steps:
        tid = uid_to_id.get(sp)
        if tid is not None:
            graph[wid].add(tid)
    visited = set()
    stack = [target_id]
    while stack:
        node = stack.pop()
        if node == parent_id:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(graph.get(node, []))
    return False


# ============== JSON 导入导出 ==============

def import_from_json(json_path: Path) -> int:
    """从 JSON 文件导入工作流（兼容旧 API：仅返回导入数量）。

    旧调用方（如 _import_and_run.py）把返回值当整数用于输出，
    因此保持 int 返回不变；需要导入告警明细请改用
    import_from_json_with_warnings。
    """
    return import_from_json_with_warnings(json_path).imported_count


def import_from_json_with_warnings(json_path: Path) -> ImportResult:
    """从 JSON 文件导入工作流，返回 ImportResult（数量 + 中文告警明细）。

    告警覆盖：脱敏 webhook 因本机无同名配置被跳过创建、
    工作流通知已启用但未绑定可用机器人（运行期将静默不发送）、
    工作流 UID 重复被跳过导入。
    """
    return import_from_json_impl(
        json_path,
        get_session=get_session,
        generate_uid=generate_uid,
        ensure_default_stage=_ensure_default_stage_in_session,
        masked_webhook_url=MASKED_WEBHOOK_URL,
    )


def export_to_json(
    json_path: Path,
    workflow_ids: List[int] | None = None,
    include_secrets: bool = False,
):
    """导出工作流到 JSON 文件。"""
    export_to_json_impl(
        json_path,
        workflow_ids=workflow_ids,
        include_secrets=include_secrets,
        get_session=get_session,
        masked_webhook_url=MASKED_WEBHOOK_URL,
    )


# ============== 工作流克隆 ==============

def clone_workflow(workflow_id: int, new_name: str = None) -> Optional[Workflow]:
    """克隆工作流（含阶段和步骤）。"""
    cloned = clone_workflow_impl(
        workflow_id,
        new_name,
        get_session=get_session,
        generate_uid=generate_uid,
    )
    if cloned is not None:
        # R1: 仍含风险路径的克隆强制重新确认（包装层二次事务，不继承原确认）。
        # F-01: get_session 现在在块退出时 close——clone_workflow_impl 返回的
        # cloned 是 detached 对象，其快照值不含此重置。重置后按 id 重读最新
        # 状态返回，保证调用方拿到的对象与库内一致。
        _reset_risky_review_after_clone(cloned.id)
        try:
            return get_workflow_by_id(cloned.id)
        except Exception:
            return cloned
    return cloned


# ============== 自动备份 ==============


def auto_backup_workflows(backup_dir: Path = None, include_secrets: bool = False) -> Path:
    """自动备份所有工作流配置到指定目录

    Args:
        backup_dir: 备份目录，默认为 APP_DATA_DIR/backups
        include_secrets: 是否在备份中保留 Webhook URL，默认脱敏以降低同步/共享泄露风险

    Returns:
        备份文件路径
    """
    from config import APP_DATA_DIR

    return auto_backup_workflows_impl(
        backup_dir=backup_dir,
        default_backup_dir=APP_DATA_DIR / "backups",
        include_secrets=include_secrets,
        export_to_json=export_to_json,
    )
# ============== L1 巨型文件治理：门面再导出 ==============
# 运行历史/StepLog、Webhook、工作流/阶段/步骤 CRUD 已拆分到 database_runs / database_webhooks / database_workflows；
# 此处再导出以保持既有 `from database import X` 调用方与测试完全不变。
from database_runs import (  # noqa: E402
    create_run_history,
    get_run_histories_by_workflow,
    get_latest_run_history,
    update_run_history,
    clear_run_histories,
    create_step_log,
    get_step_logs_by_run,
    get_recent_step_logs_for_step,
    get_step_log_summary_by_runs,
    cancel_pending_step_logs,
    update_step_log,
)
from database_webhooks import (  # noqa: E402
    is_masked_webhook_url,
    validate_webhook_url,
    list_webhooks,
    get_webhook_by_id,
    create_webhook,
    update_webhook,
    delete_webhook,
    get_webhooks_by_ids,
)
from database_workflows import (  # noqa: E402
    create_workflow,
    get_workflow_by_uid,
    get_workflow_by_id,
    get_workflow_by_name,
    search_workflows,
    get_step_by_name,
    search_steps,
    get_stage_by_name,
    search_stages,
    list_workflows,
    get_workflow_uid_name_map,
    list_recent_workflows,
    update_recent_workflow,
    update_workflow,
    delete_workflow,
    copy_workflow,
    list_stages,
    create_stage,
    update_stage,
    delete_stage,
    get_stage_order_map,
    create_step,
    copy_step,
    get_steps_by_workflow,
    update_step,
    delete_step,
    reorder_steps,
    get_step_by_id,
)
