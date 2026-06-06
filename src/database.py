# -*- coding: utf-8 -*-
"""数据库连接与 CRUD 操作"""

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
from database_import_export import (
    export_to_json_impl,
    import_from_json_impl,
    is_masked_webhook_url as _is_masked_webhook_url,
)
from database_versions import (
    get_workflow_version_impl,
    get_workflow_versions_impl,
    save_workflow_version_impl,
)
from models import Base, Workflow, WorkflowStage, Step, RunHistory, StepLog, RecentWorkflow, WebhookConfig, WorkflowVersion
from watch_rules import sanitize_workflow_watch_config

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


def _schema_cache_file() -> Path:
    """P-16: 跨进程 schema 缓存文件路径，写在 LOG_DIR 下避免污染源码目录"""
    from config import LOG_DIR
    return LOG_DIR / ".schema_version"


def _expected_schema_signature() -> str:
    """当前代码期望的 schema 签名。任何 SCHEMA_MIGRATIONS 变化都会让签名变。"""
    parts = [f"{v}:{name}" for v, name in SCHEMA_MIGRATIONS]
    return "|".join(parts)


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


def _try_read_schema_cache(engine) -> bool:
    """R2-#6: 若缓存签名一致 + 缓存版本号 >= 当前期望最大版本号，则跳过 migration 检查。

    旧版用 DB 文件 mtime 做指纹，但写一次业务数据 mtime 就变了，缓存几乎永远失效。
    现在改用 schema_versions 表中的 MAX(version)：只有真正跑过新迁移才会让版本号增长。
    """
    try:
        cache_file = _schema_cache_file()
        if not cache_file.exists():
            return False
        content = cache_file.read_text(encoding="utf-8").strip().splitlines()
        if len(content) < 2:
            return False
        cached_sig, cached_token = content[0], content[1]
        if cached_sig != _expected_schema_signature():
            return False
        # 兼容旧格式：旧值是 mtime 字符串。新格式是 "v<int>"。
        if not cached_token.startswith("v"):
            return False
        try:
            cached_version = int(cached_token[1:])
        except ValueError:
            return False
        expected_version = SCHEMA_MIGRATIONS[-1][0] if SCHEMA_MIGRATIONS else 0
        # 缓存写入时记录的版本号必须 >= 当前代码期望的最大版本号
        if cached_version < expected_version:
            return False
        # 进一步校验数据库中确实有这个版本（防止有人手动改/删了 schema_versions）
        applied = _max_applied_version(engine)
        return applied >= expected_version
    except Exception:
        return False


def _write_schema_cache(engine) -> None:
    """R2-#6: 写入当前 schema_versions 中已应用的最大版本号作为缓存指纹"""
    try:
        cache_file = _schema_cache_file()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        applied_version = _max_applied_version(engine)
        cache_file.write_text(
            f"{_expected_schema_signature()}\nv{applied_version}\n",
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("写 schema 缓存失败（不影响功能）: %s", e)


def init_db():
    """初始化数据库（进程内 + 跨进程双层幂等）"""
    global _engine, _SessionFactory, _scoped_session, _init_done

    with _init_lock:
        # P-16: 同进程内 init_db 多次调用直接返回
        if _init_done and _engine is not None:
            return _engine

        _engine = get_engine()
        _SessionFactory = sessionmaker(bind=_engine)
        # 使用scoped_session支持多线程安全
        _scoped_session = scoped_session(_SessionFactory)

        # 创建所有表（IF NOT EXISTS，已存在时仅做轻量 PRAGMA）
        Base.metadata.create_all(_engine)

        # P-16: 若缓存命中说明 schema 已经是最新版，可以跳过版本表 + migration 查询
        # R2-#6: 缓存指纹改用 schema_versions MAX(version)
        _ensure_schema_version_table(_engine)
        if not _try_read_schema_cache(_engine):
            # HA2 修复：用 schema_version 跳过已完成的迁移，避免每次启动重跑 PRAGMA table_info + ALTER
            _run_pending_migrations(_engine)
            _write_schema_cache(_engine)

        _ensure_stage_data()
        _repair_legacy_watch_configurations()
        _init_done = True

        return _engine


# ============== Schema 版本控制 ==============
# 新增迁移必须 (1) 注册到 SCHEMA_MIGRATIONS，(2) 写一个回调函数完成具体改动。
# 已执行的版本会被记录在 schema_versions 表中，不会重复执行。
SCHEMA_MIGRATIONS: list[tuple[int, str]] = [
    (1, "_migrate_v1_workflow_step_runhistory_columns"),
    (2, "_migrate_v2_version_table_and_step_uid_unique"),
    (3, "_migrate_v3_step_logs_step_run_index"),
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
    """按 SCHEMA_MIGRATIONS 顺序运行未应用的迁移"""
    applied = _get_applied_versions(engine)
    for version, func_name in SCHEMA_MIGRATIONS:
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


def _repair_legacy_watch_configurations() -> None:
    """修正旧版本遗留的高风险监听配置。"""
    with get_session() as session:
        workflows = session.query(Workflow).filter(Workflow.watch_enabled.is_(True)).all()
        changed = False
        for workflow in workflows:
            updated, folders, enabled = sanitize_workflow_watch_config(
                workflow_name=workflow.name,
                watch_enabled=bool(workflow.watch_enabled),
                watch_folders=workflow.get_watch_folders(),
                steps=workflow.steps,
            )
            if not updated:
                continue
            workflow.watch_enabled = bool(enabled)
            workflow.set_watch_folders(folders)
            workflow.updated_at = datetime.now()
            changed = True
            logger.info(
                "已自动修正旧监听配置: workflow=%s, watch_enabled=%s, watch_folders=%s",
                workflow.name,
                workflow.watch_enabled,
                folders,
            )
        if changed:
            session.commit()


def _migrate_v1_workflow_step_runhistory_columns(engine):
    """v1: 补齐 workflow / step / run_history 早期版本未包含的列"""
    _ensure_workflow_columns(engine)
    _ensure_step_columns(engine)
    _ensure_run_history_columns(engine)


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
                "DELETE FROM steps WHERE workflow_id=:w AND uid=:u AND id != :k"
            ), {"w": wf_id, "u": uid, "k": keep_id})
        # 2) 创建 unique index（IF NOT EXISTS 幂等）
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_steps_workflow_uid "
                "ON steps(workflow_id, uid)"
            ))
        except Exception as e:
            logger.warning("创建 steps 唯一索引失败（可能存在残余重复）: %s", e)


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

    注意：不在此处调用 scoped_session.remove()，
    因为 database.py 中的函数经常返回 ORM 对象供调用方使用，
    remove() 会使 session 关闭导致返回对象变成 detached 状态。
    scoped_session 会在同一线程中复用同一 session，保证线程安全。

    异常路径会调用 remove() 以避免污染的 session 在线程中残留。
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


def _wal_checkpoint(session: Session) -> None:
    """跨 session 一致性兜底：将 WAL 写入主数据库（PASSIVE 不阻塞）

    在终态写入（status=success/failure/cancelled）后调用，
    确保跨线程读 session 能立刻看到最新状态。
    """
    try:
        session.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
    except Exception as e:
        logger.debug("WAL checkpoint 失败（不影响当前事务）: %s", e)


def generate_uid() -> str:
    """生成唯一 ID"""
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


# ============== Workflow CRUD ==============

def create_workflow(
    name: str,
    description: str = "",
    chart_theme: str = "default",
    parallel_enabled: bool = False,
    max_workers: int = 2
) -> Workflow:
    """创建工作流"""
    with get_session() as session:
        workflow = Workflow(
            uid=generate_uid(),
            name=name,
            description=description,
            chart_theme=chart_theme,
            parallel_enabled=parallel_enabled,
            max_workers=max_workers
        )
        session.add(workflow)
        session.commit()
        session.refresh(workflow)
        # 默认用途阶段：避免旧行为变化（只有一个阶段时等价于原执行）
        _ensure_default_stage_in_session(session, workflow.id)
        session.commit()
        return workflow


def get_workflow_by_uid(uid: str) -> Optional[Workflow]:
    """根据 UID 获取工作流"""
    with get_session() as session:
        return session.query(Workflow).filter(Workflow.uid == uid).first()


def get_workflow_by_id(workflow_id: int) -> Optional[Workflow]:
    """根据 ID 获取工作流"""
    with get_session() as session:
        return session.query(Workflow).filter(Workflow.id == workflow_id).first()


def get_workflow_by_name(name: str) -> Optional[Workflow]:
    """根据名称获取工作流（精确匹配）"""
    with get_session() as session:
        return session.query(Workflow).filter(Workflow.name == name.strip()).first()


def search_workflows(keyword: str) -> List[Workflow]:
    """根据关键词模糊搜索工作流（名称或UID包含关键词）"""
    with get_session() as session:
        pattern = f"%{keyword.strip()}%"
        return (
            session.query(Workflow)
            .filter(
                (Workflow.name.ilike(pattern)) | (Workflow.uid.ilike(pattern))
            )
            .all()
        )


def get_step_by_name(workflow_id: int, name: str) -> Optional["Step"]:
    """根据名称获取工作流中的步骤（精确匹配）"""
    with get_session() as session:
        return (
            session.query(Step)
            .filter(Step.workflow_id == workflow_id, Step.name == name.strip())
            .first()
        )


def search_steps(workflow_id: int, keyword: str) -> List["Step"]:
    """根据关键词模糊搜索工作流中的步骤"""
    with get_session() as session:
        pattern = f"%{keyword.strip()}%"
        return (
            session.query(Step)
            .filter(
                Step.workflow_id == workflow_id,
                (Step.name.ilike(pattern)) | (Step.uid.ilike(pattern)),
            )
            .order_by(Step.order)
            .all()
        )


def get_stage_by_name(workflow_id: int, name: str) -> Optional["WorkflowStage"]:
    """根据名称获取工作流中的阶段（精确匹配）"""
    with get_session() as session:
        return (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == workflow_id, WorkflowStage.name == name.strip())
            .first()
        )


def search_stages(workflow_id: int, keyword: str) -> List["WorkflowStage"]:
    """根据关键词模糊搜索工作流中的阶段"""
    with get_session() as session:
        pattern = f"%{keyword.strip()}%"
        return (
            session.query(WorkflowStage)
            .filter(
                WorkflowStage.workflow_id == workflow_id,
                WorkflowStage.name.ilike(pattern),
            )
            .order_by(WorkflowStage.order)
            .all()
        )


def list_workflows(with_steps: bool = False) -> List[Workflow]:
    """获取所有工作流

    Args:
        with_steps: 是否预加载步骤关系（避免 N+1 查询问题）
    """
    with get_session() as session:
        query = session.query(Workflow)
        if with_steps:
            query = query.options(joinedload(Workflow.steps))
        return query.order_by(Workflow.created_at.desc()).all()


def get_workflow_uid_name_map() -> dict[str, str]:
    """获取所有工作流的 uid -> name 映射（CA1 修复：避免 UI 频繁全表加载 ORM 对象）

    用于 step_table 显示 sub_workflow 步骤的目标工作流名称等场景，
    单次轻量查询代替 list_workflows() 全 ORM 加载。
    """
    with get_session() as session:
        rows = session.query(Workflow.uid, Workflow.name).all()
        return {uid: name for uid, name in rows}


def list_recent_workflows(limit: int = 10) -> List[str]:
    """获取最近使用的子工作流 UID"""
    with get_session() as session:
        items = session.query(RecentWorkflow).order_by(RecentWorkflow.updated_at.desc()).limit(limit).all()
        return [item.workflow_uid for item in items]


def update_recent_workflow(uid: str):
    """更新最近使用的子工作流"""
    with get_session() as session:
        item = session.query(RecentWorkflow).filter(RecentWorkflow.workflow_uid == uid).first()
        if not item:
            item = RecentWorkflow(workflow_uid=uid)
            session.add(item)
        item.updated_at = datetime.now()
        session.commit()


def update_workflow(workflow_id: int, **kwargs) -> Optional[Workflow]:
    """更新工作流"""
    _validate_update_fields("Workflow", kwargs, WORKFLOW_UPDATE_FIELDS)
    with get_session() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            for key, value in kwargs.items():
                setattr(workflow, key, value)
            workflow.updated_at = datetime.now()
            session.commit()
            session.refresh(workflow)
        # #9: 工作流结构可能变更（sub_workflow 步骤引用等），主动失效环检测缓存
        invalidate_cycle_check_cache()
        return workflow


def ensure_single_script_step(
    workflow_id: int,
    step_type: str,
    script_path: str,
    args: Optional[List[str]] = None,
    cwd: Optional[str] = None
) -> Optional[Step]:
    """确保存在单脚本步骤"""
    with get_session() as session:
        default_stage = _ensure_default_stage_in_session(session, workflow_id)
        step = session.query(Step).filter(
            Step.workflow_id == workflow_id,
            Step.uid == "single_script"
        ).first()
        if not step:
            step = Step(
                workflow_id=workflow_id,
                uid="single_script",
                order=0,
                name="单脚本模式",
                stage_uid=default_stage.uid,
                step_type=step_type,
                script_path=script_path,
                cwd=cwd,
                is_gate=False,
                is_parallel=False
            )
            session.add(step)
        else:
            step.step_type = step_type
            step.script_path = script_path
            step.cwd = cwd
            if not step.stage_uid:
                step.stage_uid = default_stage.uid
        if args is not None:
            step.set_args(args)
        session.commit()
        session.refresh(step)
        return step


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


def delete_workflow(workflow_id: int) -> bool:
    """删除工作流"""
    with get_session() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            session.delete(workflow)
            session.commit()
            return True
        return False


def copy_workflow(workflow_id: int, new_name: str) -> Optional[Workflow]:
    """复制工作流。

    兼容旧 API；实际实现统一委托给 clone_workflow，确保步骤依赖 UID 会被重映射。
    """
    return clone_workflow(workflow_id, new_name)


# ============== Stage CRUD ==============

def list_stages(workflow_id: int) -> List[WorkflowStage]:
    """获取工作流的用途阶段（按 order 排序）"""
    with get_session() as session:
        return (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == workflow_id)
            .order_by(WorkflowStage.order.asc())
            .all()
        )


def create_stage(
    workflow_id: int,
    name: str = "新阶段",
    order: Optional[int] = None,
    color: Optional[str] = None,
) -> WorkflowStage:
    """创建用途阶段（插入到指定 order，后续阶段自动顺延）"""
    with get_session() as session:
        _ensure_default_stage_in_session(session, workflow_id)

        if order is None:
            max_order = session.query(func.max(WorkflowStage.order)).filter(
                WorkflowStage.workflow_id == workflow_id
            ).scalar()
            order = int(max_order or 0) + 1
        else:
            session.query(WorkflowStage).filter(
                WorkflowStage.workflow_id == workflow_id,
                WorkflowStage.order >= order,
            ).update({WorkflowStage.order: WorkflowStage.order + 1})

        stage = WorkflowStage(
            uid=generate_uid(),
            workflow_id=workflow_id,
            name=name.strip() or "新阶段",
            order=int(order),
            color=color,
        )
        session.add(stage)
        session.commit()
        session.refresh(stage)
        return stage


def update_stage(stage_uid: str, **kwargs) -> Optional[WorkflowStage]:
    """更新用途阶段"""
    _validate_update_fields("WorkflowStage", kwargs, STAGE_UPDATE_FIELDS)
    with get_session() as session:
        stage = session.query(WorkflowStage).filter(WorkflowStage.uid == stage_uid).first()
        if not stage:
            return None
        for key, value in kwargs.items():
            setattr(stage, key, value)
        stage.updated_at = datetime.now()
        session.commit()
        session.refresh(stage)
        return stage


def delete_stage(stage_uid: str) -> bool:
    """删除用途阶段（仅删除空阶段；默认阶段不可删除）"""
    with get_session() as session:
        stage = session.query(WorkflowStage).filter(WorkflowStage.uid == stage_uid).first()
        if not stage:
            return False
        # 默认阶段：保护（用 created_at 最早的阶段作为「默认阶段」真相源，避免 reorder 后被误删）
        default_stage = (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == stage.workflow_id)
            .order_by(WorkflowStage.created_at.asc(), WorkflowStage.id.asc())
            .first()
        )
        if default_stage and default_stage.uid == stage.uid:
            return False
        steps_count = session.query(func.count(Step.id)).filter(
            Step.workflow_id == stage.workflow_id,
            Step.stage_uid == stage.uid,
        ).scalar()
        if int(steps_count or 0) > 0:
            return False
        session.delete(stage)
        session.commit()
        return True


def get_stage_order_map(workflow_id: int) -> dict[str, int]:
    """获取 stage_uid -> stage_order 的映射（确保至少有默认阶段）"""
    with get_session() as session:
        _ensure_default_stage_in_session(session, workflow_id)
        stages = (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == workflow_id)
            .order_by(WorkflowStage.order.asc())
            .all()
        )
        return {s.uid: int(s.order or 0) for s in stages}


# ============== Step CRUD ==============

def create_step(
    workflow_id: int,
    name: str,
    step_type: str = "python",
    script_path: str = "",
    order: int = 0,
    stage_uid: str = ""
) -> Optional[Step]:
    """创建步骤"""
    with get_session() as session:
        if not stage_uid:
            default_stage = _ensure_default_stage_in_session(session, workflow_id)
            stage_uid = default_stage.uid
        step = Step(
            workflow_id=workflow_id,
            uid=generate_uid(),
            name=name,
            step_type=step_type,
            script_path=script_path,
            order=order,
            stage_uid=stage_uid,
        )
        session.add(step)
        session.commit()
        session.refresh(step)
        # #9: 新步骤可能引入 sub_workflow 引用，主动失效环检测缓存
        invalidate_cycle_check_cache()
        return step


def copy_step(step_id: int) -> Optional[Step]:
    """复制步骤（在同一工作流中创建一条副本）"""
    with get_session() as session:
        source = session.query(Step).filter(Step.id == step_id).first()
        if not source:
            return None

        max_order = session.query(func.max(Step.order)).filter(
            Step.workflow_id == source.workflow_id
        ).scalar()
        new_order = int(max_order or 0) + 1

        new_step = Step(
            workflow_id=source.workflow_id,
            uid=generate_uid(),
            order=new_order,
            name=f"{source.name} (副本)",
            stage_uid=source.stage_uid,
            step_type=source.step_type,
            script_path=source.script_path,
            args=source.args,
            cwd=source.cwd,
            is_gate=source.is_gate,
            is_parallel=source.is_parallel,
            depends_on=source.depends_on,
            chart_theme=source.chart_theme,
            timeout_seconds=source.timeout_seconds,
            retry_count=source.retry_count,
            skip_on_success=source.skip_on_success,
        )
        session.add(new_step)
        session.commit()
        session.refresh(new_step)
        return new_step


def get_steps_by_workflow(workflow_id: int) -> List[Step]:
    """获取工作流的所有步骤"""
    with get_session() as session:
        return session.query(Step).filter(
            Step.workflow_id == workflow_id
        ).order_by(Step.order).all()


def update_step(step_id: int, **kwargs) -> Optional[Step]:
    """更新步骤"""
    _validate_update_fields("Step", kwargs, STEP_UPDATE_FIELDS)
    with get_session() as session:
        step = session.query(Step).filter(Step.id == step_id).first()
        if step:
            for key, value in kwargs.items():
                setattr(step, key, value)
            step.updated_at = datetime.now()
            session.commit()
            session.refresh(step)
        # #9: 步骤可能变更 sub_workflow 引用，主动失效环检测缓存
        invalidate_cycle_check_cache()
        return step


def delete_step(step_id: int) -> bool:
    """删除步骤"""
    with get_session() as session:
        step = session.query(Step).filter(Step.id == step_id).first()
        if step:
            session.delete(step)
            session.commit()
            # #9: 步骤删除可能移除 sub_workflow 引用，主动失效环检测缓存
            invalidate_cycle_check_cache()
            return True
        return False


def reorder_steps(workflow_id: int, step_orders: dict) -> bool:
    """重新排序步骤

    Args:
        workflow_id: 工作流 ID
        step_orders: {step_id: new_order, ...}
    """
    with get_session() as session:
        steps = session.query(Step).filter(
            Step.id.in_(step_orders.keys()),
            Step.workflow_id == workflow_id
        ).all()
        for step in steps:
            if step.id in step_orders:
                step.order = step_orders[step.id]
        session.commit()
        return True


# ============== RunHistory CRUD ==============

def create_run_history(
    workflow_id: int,
    run_mode: str = "full",
    run_mode_param: str = None,
    reason: str = "manual",
    trace_id: str = None,
    parent_run_id: str = None
) -> RunHistory:
    """创建运行历史

    Args:
        workflow_id: 工作流 ID
        run_mode: 运行模式 (full/from_step/only_step/retry_failed)
        run_mode_param: 运行模式参数
        reason: 触发原因 (manual/watch/sub_workflow)
        trace_id: 追踪 ID（同一次完整执行的顶级 ID，子工作流继承父级）
        parent_run_id: 父运行 ID（子工作流设置，用于关联父工作流）
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    with get_session() as session:
        run_history = RunHistory(
            workflow_id=workflow_id,
            run_id=run_id,
            status="pending",
            reason=reason,
            run_mode=run_mode,
            run_mode_param=run_mode_param,
            trace_id=trace_id or run_id,
            parent_run_id=parent_run_id
        )
        session.add(run_history)
        session.commit()
        session.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
        session.refresh(run_history)
        return run_history


def get_run_histories_by_workflow(
    workflow_id: int, 
    limit: int = 20
) -> List[RunHistory]:
    """获取工作流的运行历史"""
    with get_session() as session:
        return session.query(RunHistory).filter(
            RunHistory.workflow_id == workflow_id
        ).order_by(RunHistory.start_time.desc()).limit(limit).all()


def get_latest_run_history(
    workflow_id: int,
    include_statuses: Optional[List[str]] = None,
    exclude_statuses: Optional[List[str]] = None,
    only_finished: bool = False,
    exclude_run_history_id: Optional[int] = None,
) -> Optional[RunHistory]:
    """获取最新的运行历史"""
    with get_session() as session:
        query = session.query(RunHistory).filter(
            RunHistory.workflow_id == workflow_id
        )
        if include_statuses:
            query = query.filter(RunHistory.status.in_(list(include_statuses)))
        if exclude_statuses:
            query = query.filter(~RunHistory.status.in_(list(exclude_statuses)))
        if only_finished:
            query = query.filter(RunHistory.end_time.isnot(None))
        if exclude_run_history_id is not None:
            query = query.filter(RunHistory.id != exclude_run_history_id)
        return query.order_by(RunHistory.start_time.desc(), RunHistory.id.desc()).first()


def update_run_history(run_history_id: int, **kwargs) -> Optional[RunHistory]:
    """更新运行历史"""
    _validate_update_fields("RunHistory", kwargs, RUN_HISTORY_UPDATE_FIELDS)
    with get_session() as session:
        run_history = session.query(RunHistory).filter(
            RunHistory.id == run_history_id
        ).first()
        if run_history:
            for key, value in kwargs.items():
                setattr(run_history, key, value)
            session.commit()
            # 终态写入后触发 WAL checkpoint，保证跨 session 一致性
            if kwargs.get("status") in ("success", "failure", "cancelled"):
                _wal_checkpoint(session)
            session.refresh(run_history)
        return run_history


# ============== StepLog CRUD ==============


def clear_run_histories(workflow_id: int) -> int:
    """清除指定工作流的所有运行历史（优化：使用批量删除，避免加载所有对象）

    Returns:
        删除的记录数
    """
    with get_session() as session:
        # 先获取所有历史ID（仅查询ID，不加载完整对象）
        history_ids = [
            h.id for h in session.query(RunHistory.id).filter(
                RunHistory.workflow_id == workflow_id
            )
        ]

        if not history_ids:
            return 0

        # 批量删除关联的步骤日志
        session.query(StepLog).filter(
            StepLog.run_history_id.in_(history_ids)
        ).delete(synchronize_session=False)

        # 批量删除运行历史
        count = session.query(RunHistory).filter(
            RunHistory.workflow_id == workflow_id
        ).delete(synchronize_session=False)

        session.commit()
        return count

def create_step_log(
    run_history_id: int,
    step_id: int,
    order: int = 0
) -> StepLog:
    """创建步骤日志"""
    last_error = None
    for attempt in range(3):
        with get_session() as session:
            step_log = StepLog(
                run_history_id=run_history_id,
                step_id=step_id,
                order=order,
                status="pending"
            )
            session.add(step_log)
            try:
                session.commit()
                session.refresh(step_log)
                return step_log
            except Exception as e:
                session.rollback()
                last_error = e
                if attempt < 2:
                    session.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
                    time.sleep(0.1 * (attempt + 1))
    raise last_error


def get_step_logs_by_run(run_history_id: int) -> List[StepLog]:
    """获取运行的所有步骤日志"""
    with get_session() as session:
        return session.query(StepLog).options(joinedload(StepLog.step)).filter(
            StepLog.run_history_id == run_history_id
        ).order_by(StepLog.order).all()


def get_recent_step_logs_for_step(workflow_id: int, step_id: int, limit: int = 20) -> List[StepLog]:
    """P-11: 一次查询拿到指定 step 在最近 N 个 run 中的所有 StepLog（按 run 创建时间倒序）。

    替代"循环 RunHistory → 每条查 StepLog"的 N+1 模式，给 UI 找最近一次日志路径用。
    """
    with get_session() as session:
        recent_run_ids_subq = (
            session.query(RunHistory.id)
            .filter(RunHistory.workflow_id == workflow_id)
            .order_by(RunHistory.start_time.desc().nullslast(), RunHistory.id.desc())
            .limit(limit)
            .subquery()
        )
        return (
            session.query(StepLog)
            .filter(
                StepLog.step_id == step_id,
                StepLog.run_history_id.in_(recent_run_ids_subq),
            )
            .order_by(StepLog.run_history_id.desc())
            .all()
        )


def get_step_log_summary_by_runs(run_history_ids: List[int]) -> dict[int, dict[str, int]]:
    """批量汇总多个运行的步骤状态统计。"""
    if not run_history_ids:
        return {}

    base_statuses = ["success", "failure", "skipped", "cancelled", "running", "pending"]
    summary = {
        int(run_history_id): {status: 0 for status in base_statuses}
        for run_history_id in run_history_ids
    }

    with get_session() as session:
        rows = session.query(
            StepLog.run_history_id,
            StepLog.status,
            func.count(StepLog.id)
        ).filter(
            StepLog.run_history_id.in_(run_history_ids)
        ).group_by(
            StepLog.run_history_id,
            StepLog.status
        ).all()

    for run_history_id, status, count in rows:
        bucket = summary.setdefault(int(run_history_id), {key: 0 for key in base_statuses})
        status_key = str(status or "pending")
        bucket.setdefault(status_key, 0)
        bucket[status_key] = int(count or 0)

    return summary


def cancel_pending_step_logs(run_history_id: int, error_message: str = "用户强制停止") -> int:
    """R4-#9: 批量把指定 run 下所有 pending/running 的 step_logs 改为 cancelled。

    使用单次 UPDATE 替代 N 次 update_step_log，避免 N+1 commit。
    返回被改动的行数。
    """
    now = datetime.now()
    try:
        with get_session() as session:
            affected = (
                session.query(StepLog)
                .filter(
                    StepLog.run_history_id == run_history_id,
                    StepLog.status.in_(("pending", "running")),
                )
                .update(
                    {
                        StepLog.status: "cancelled",
                        StepLog.end_time: now,
                        StepLog.error_message: error_message,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return int(affected or 0)
    except Exception as e:
        logger.warning("批量取消 step_logs 失败: %s", e)
        return 0


def update_step_log(step_log_id: int, **kwargs) -> Optional[StepLog]:
    """更新步骤日志

    R4-#4: 终态写入不再每次触发 WAL checkpoint，依赖 SQLite 默认 auto-checkpoint
    (wal_autocheckpoint=1000 pages)；run_history 终结时由 update_run_history 一次性
    checkpoint，足以保证跨进程一致性。
    """
    _validate_update_fields("StepLog", kwargs, STEP_LOG_UPDATE_FIELDS)
    with get_session() as session:
        step_log = session.query(StepLog).filter(StepLog.id == step_log_id).first()
        if step_log:
            for key, value in kwargs.items():
                setattr(step_log, key, value)
            session.commit()
            session.refresh(step_log)
        return step_log


# ============== JSON 导入导出 ==============

def is_masked_webhook_url(value: str | None) -> bool:
    """判断导入值是否为脱敏占位符。"""
    return _is_masked_webhook_url(value, MASKED_WEBHOOK_URL)


def import_from_json(json_path: Path) -> int:
    """从 JSON 文件导入工作流。"""
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


# ============== Webhook CRUD ==============

def list_webhooks() -> List[WebhookConfig]:
    """获取所有 Webhook 配置

    M8: 返回前 expunge，确保对象在 session 之外的属性访问不会触发刷新。
    """
    with get_session() as session:
        rows = session.query(WebhookConfig).order_by(WebhookConfig.name).all()
        for row in rows:
            session.expunge(row)
        return rows


def get_webhook_by_id(webhook_id: int) -> Optional[WebhookConfig]:
    """根据 ID 获取 Webhook

    M8: 返回前 expunge，确保对象在 session 之外的属性访问不会触发刷新。
    """
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            session.expunge(webhook)
        return webhook


def create_webhook(
    name: str,
    webhook_url: str,
    keyword: str = "",
    description: str = ""
) -> WebhookConfig:
    """创建 Webhook 配置"""
    with get_session() as session:
        webhook = WebhookConfig(
            name=name,
            webhook_url=webhook_url,
            keyword=keyword,
            description=description
        )
        session.add(webhook)
        session.commit()
        session.refresh(webhook)
        session.expunge(webhook)
        return webhook


def update_webhook(webhook_id: int, **kwargs) -> Optional[WebhookConfig]:
    """更新 Webhook 配置"""
    _validate_update_fields("WebhookConfig", kwargs, WEBHOOK_UPDATE_FIELDS)
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            for key, value in kwargs.items():
                setattr(webhook, key, value)
            webhook.updated_at = datetime.now()
            session.commit()
            session.refresh(webhook)
            session.expunge(webhook)
        return webhook


def delete_webhook(webhook_id: int) -> bool:
    """删除 Webhook 配置"""
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            session.delete(webhook)
            session.commit()
            return True
        return False


def get_webhooks_by_ids(webhook_ids: List[int]) -> List[WebhookConfig]:
    """根据 ID 列表获取多个 Webhook"""
    if not webhook_ids:
        return []
    with get_session() as session:
        return session.query(WebhookConfig).filter(WebhookConfig.id.in_(webhook_ids)).all()


# ============== 工作流克隆 ==============

def clone_workflow(workflow_id: int, new_name: str = None) -> Optional[Workflow]:
    """克隆工作流（含阶段和步骤）。"""
    return clone_workflow_impl(
        workflow_id,
        new_name,
        get_session=get_session,
        generate_uid=generate_uid,
    )


# ============== 配置版本控制 ==============

def save_workflow_version(workflow_id: int, reason: str = None) -> Optional[int]:
    """保存工作流当前配置的快照版本

    Args:
        workflow_id: 工作流 ID
        reason: 变更原因

    Returns:
        版本号
    """
    return save_workflow_version_impl(
        workflow_id,
        reason=reason,
        session_factory=get_session,
    )


def get_workflow_versions(workflow_id: int, limit: int = 20) -> List[WorkflowVersion]:
    """获取工作流的版本历史"""
    return get_workflow_versions_impl(
        workflow_id,
        limit=limit,
        session_factory=get_session,
    )


def get_workflow_version(version_id: int) -> Optional[WorkflowVersion]:
    """获取指定版本"""
    return get_workflow_version_impl(version_id, session_factory=get_session)


def get_step_by_id(step_id: int):
    """根据 ID 获取单个步骤"""
    with get_session() as session:
        return session.query(Step).filter(Step.id == step_id).first()


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
