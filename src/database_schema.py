"""Additive schema implementations; database retains the late-bound registry facade."""
import json
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def _migrate_v1_workflow_step_runhistory_columns(engine):
    """v1: 补齐 workflow / step / run_history 早期版本未包含的列"""
    import database
    database._ensure_workflow_columns(engine)
    database._ensure_step_columns(engine)
    database._ensure_run_history_columns(engine)


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
    import database
    database._ensure_version_table(engine)
    database._ensure_step_uid_unique(engine)


def _migrate_v3_step_logs_step_run_index(engine):
    """v3: R2-#5 为 step_logs 加 (step_id, run_history_id) 组合索引"""
    with engine.begin() as conn:
        try:
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_step_logs_step_run "
                "ON step_logs(step_id, run_history_id)"
            ))
        except (SQLAlchemyError, OSError, RuntimeError) as e:
            logger.warning("创建 ix_step_logs_step_run 失败: %s", e)


def _migrate_v4_workflow_version_unique(engine):
    """v4: 为 workflow_versions 建立 (workflow_id, version) 唯一约束。"""
    import database
    database._ensure_version_table(engine)
    database._ensure_workflow_version_unique(engine)


def _migrate_v5_webhook_name_unique(engine):
    """v5: 清理重复 webhook 名称后建立唯一索引。"""
    import database
    database._ensure_webhook_name_unique(engine)


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
        except (SQLAlchemyError, OSError, RuntimeError):
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
