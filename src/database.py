# -*- coding: utf-8 -*-
"""数据库连接与 CRUD 操作"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from sqlalchemy import create_engine, event, text, func
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_PATH
from models import Base, Workflow, WorkflowStage, Step, RunHistory, StepLog, RecentWorkflow, WebhookConfig


# 创建数据库引擎
def get_engine():
    """获取数据库引擎"""
    engine = create_engine(
        f"sqlite:///{DATABASE_PATH}",
        echo=False,
        connect_args={"check_same_thread": False}
    )
    
    # 启用外键约束
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    
    return engine


# 全局引擎和会话工厂
_engine = None
_SessionFactory = None


def init_db():
    """初始化数据库"""
    global _engine, _SessionFactory
    
    _engine = get_engine()
    _SessionFactory = sessionmaker(bind=_engine)
    
    # 创建所有表
    Base.metadata.create_all(_engine)
    _ensure_workflow_columns(_engine)
    _ensure_step_columns(_engine)
    _ensure_stage_data()
    
    return _engine


def _ensure_workflow_columns(engine):
    """兼容老库：补齐新增字段"""
    with engine.connect() as conn:
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


def _ensure_step_columns(engine):
    """兼容老库：补齐 steps 表新增字段"""
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(steps)")).fetchall()
        existing = {row[1] for row in rows}
        alter_sql = []
        if "skip_on_success" not in existing:
            alter_sql.append("ALTER TABLE steps ADD COLUMN skip_on_success INTEGER DEFAULT 0")
        if "stage_uid" not in existing:
            alter_sql.append("ALTER TABLE steps ADD COLUMN stage_uid VARCHAR(64)")
        for sql in alter_sql:
            conn.execute(text(sql))


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
    """兼容老库：为所有工作流补齐默认阶段，并为旧步骤填充 stage_uid"""
    with get_session() as session:
        workflows = session.query(Workflow).all()
        for wf in workflows:
            default_stage = _ensure_default_stage_in_session(session, wf.id)
            session.query(Step).filter(
                Step.workflow_id == wf.id,
                Step.stage_uid.is_(None),
            ).update({Step.stage_uid: default_stage.uid})
        session.commit()


def get_session() -> Session:
    """获取数据库会话"""
    global _SessionFactory
    
    if _SessionFactory is None:
        init_db()
    
    return _SessionFactory()


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


def list_workflows() -> List[Workflow]:
    """获取所有工作流"""
    with get_session() as session:
        return session.query(Workflow).order_by(Workflow.created_at.desc()).all()


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
    with get_session() as session:
        workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow:
            for key, value in kwargs.items():
                if hasattr(workflow, key):
                    setattr(workflow, key, value)
            workflow.updated_at = datetime.now()
            session.commit()
            session.refresh(workflow)
        return workflow


def ensure_single_script_step(
    workflow_id: int,
    step_type: str,
    script_path: str,
    args: list | None = None,
    cwd: str | None = None
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
    """检测跨工作流循环依赖"""
    workflows = list_workflows()
    uid_to_id = {w.uid: w.id for w in workflows}
    target_id = uid_to_id.get(target_uid)
    if target_id is None:
        return False
    if target_id == parent_id:
        return True
    graph = {w.id: set() for w in workflows}
    for wf in workflows:
        steps = get_steps_by_workflow(wf.id)
        for step in steps:
            if step.step_type == "sub_workflow" and step.script_path:
                tid = uid_to_id.get(step.script_path)
                if tid is not None:
                    graph[wf.id].add(tid)
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
    """复制工作流"""
    with get_session() as session:
        source = session.query(Workflow).filter(Workflow.id == workflow_id).first()
        if not source:
            return None
        
        # 创建新工作流
        new_workflow = Workflow(
            uid=generate_uid(),
            name=new_name,
            description=source.description,
            chart_theme=source.chart_theme,
            parallel_enabled=source.parallel_enabled,
            max_workers=source.max_workers,
            notify_config=source.notify_config,
            watch_enabled=source.watch_enabled,
            watch_mode=source.watch_mode,
            watch_folders=source.watch_folders,
            cooldown_seconds=source.cooldown_seconds,
            settle_seconds=source.settle_seconds,
            log_retention_days=source.log_retention_days
        )
        session.add(new_workflow)
        session.flush()  # 获取新 ID

        # 复制用途阶段（为稳定：生成新 uid，并建立 old_uid -> new_uid 映射）
        _ensure_default_stage_in_session(session, source.id)
        source_stages = (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == source.id)
            .order_by(WorkflowStage.order.asc())
            .all()
        )
        stage_uid_map: dict[str, str] = {}
        for st in source_stages:
            new_stage_uid = generate_uid()
            stage_uid_map[st.uid] = new_stage_uid
            session.add(
                WorkflowStage(
                    uid=new_stage_uid,
                    workflow_id=new_workflow.id,
                    name=st.name,
                    order=st.order,
                    color=st.color,
                )
            )
        session.flush()
        # 若源工作流没有阶段（理论上不会），确保新工作流至少有默认阶段
        _ensure_default_stage_in_session(session, new_workflow.id)
        
        # 复制步骤
        for step in source.steps:
            new_step = Step(
                workflow_id=new_workflow.id,
                uid=generate_uid(),
                order=step.order,
                name=step.name,
                stage_uid=stage_uid_map.get(step.stage_uid) if step.stage_uid else None,
                step_type=step.step_type,
                script_path=step.script_path,
                args=step.args,
                cwd=step.cwd,
                is_gate=step.is_gate,
                is_parallel=step.is_parallel,
                depends_on=step.depends_on,
                chart_theme=step.chart_theme,
                timeout_seconds=step.timeout_seconds,
                retry_count=step.retry_count,
                skip_on_success=step.skip_on_success
            )
            session.add(new_step)
        
        session.commit()
        session.refresh(new_workflow)
        return new_workflow


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
    with get_session() as session:
        stage = session.query(WorkflowStage).filter(WorkflowStage.uid == stage_uid).first()
        if not stage:
            return None
        for key, value in kwargs.items():
            if hasattr(stage, key):
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
        # 默认阶段：保护（用 created_at 最早的阶段作为“默认阶段”真相源，避免 reorder 后被误删）
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
    order: int = 0
) -> Optional[Step]:
    """创建步骤"""
    with get_session() as session:
        default_stage = _ensure_default_stage_in_session(session, workflow_id)
        step = Step(
            workflow_id=workflow_id,
            uid=generate_uid(),
            name=name,
            step_type=step_type,
            script_path=script_path,
            order=order,
            stage_uid=default_stage.uid,
        )
        session.add(step)
        session.commit()
        session.refresh(step)
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
    with get_session() as session:
        step = session.query(Step).filter(Step.id == step_id).first()
        if step:
            for key, value in kwargs.items():
                if hasattr(step, key):
                    setattr(step, key, value)
            step.updated_at = datetime.now()
            session.commit()
            session.refresh(step)
        return step


def delete_step(step_id: int) -> bool:
    """删除步骤"""
    with get_session() as session:
        step = session.query(Step).filter(Step.id == step_id).first()
        if step:
            session.delete(step)
            session.commit()
            return True
        return False


def reorder_steps(workflow_id: int, step_orders: dict) -> bool:
    """重新排序步骤
    
    Args:
        workflow_id: 工作流 ID
        step_orders: {step_id: new_order, ...}
    """
    with get_session() as session:
        for step_id, new_order in step_orders.items():
            step = session.query(Step).filter(Step.id == step_id).first()
            if step and step.workflow_id == workflow_id:
                step.order = new_order
        session.commit()
        return True


# ============== RunHistory CRUD ==============

def create_run_history(
    workflow_id: int,
    run_mode: str = "full",
    run_mode_param: str = None,
    reason: str = "manual"
) -> RunHistory:
    """创建运行历史"""
    with get_session() as session:
        run_history = RunHistory(
            workflow_id=workflow_id,
            run_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            status="pending",
            reason=reason,
            run_mode=run_mode,
            run_mode_param=run_mode_param
        )
        session.add(run_history)
        session.commit()
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


def get_latest_run_history(workflow_id: int) -> Optional[RunHistory]:
    """获取最新的运行历史"""
    with get_session() as session:
        return session.query(RunHistory).filter(
            RunHistory.workflow_id == workflow_id
        ).order_by(RunHistory.start_time.desc()).first()


def update_run_history(run_history_id: int, **kwargs) -> Optional[RunHistory]:
    """更新运行历史"""
    with get_session() as session:
        run_history = session.query(RunHistory).filter(
            RunHistory.id == run_history_id
        ).first()
        if run_history:
            for key, value in kwargs.items():
                if hasattr(run_history, key):
                    setattr(run_history, key, value)
            session.commit()
            session.refresh(run_history)
        return run_history


# ============== StepLog CRUD ==============


def clear_run_histories(workflow_id: int) -> int:
    """清除指定工作流的所有运行历史
    
    Returns:
        删除的记录数
    """
    with get_session() as session:
        # 先删除关联的步骤日志
        histories = session.query(RunHistory).filter(
            RunHistory.workflow_id == workflow_id
        ).all()
        
        count = 0
        for history in histories:
            # 删除步骤日志
            session.query(StepLog).filter(
                StepLog.run_history_id == history.id
            ).delete()
            count += 1
        
        # 删除运行历史
        session.query(RunHistory).filter(
            RunHistory.workflow_id == workflow_id
        ).delete()
        
        session.commit()
        return count

def create_step_log(
    run_history_id: int,
    step_id: int,
    order: int = 0
) -> StepLog:
    """创建步骤日志"""
    with get_session() as session:
        step_log = StepLog(
            run_history_id=run_history_id,
            step_id=step_id,
            order=order,
            status="pending"
        )
        session.add(step_log)
        session.commit()
        session.refresh(step_log)
        return step_log


def get_step_logs_by_run(run_history_id: int) -> List[StepLog]:
    """获取运行的所有步骤日志"""
    with get_session() as session:
        return session.query(StepLog).filter(
            StepLog.run_history_id == run_history_id
        ).order_by(StepLog.order).all()


def update_step_log(step_log_id: int, **kwargs) -> Optional[StepLog]:
    """更新步骤日志"""
    with get_session() as session:
        step_log = session.query(StepLog).filter(StepLog.id == step_log_id).first()
        if step_log:
            for key, value in kwargs.items():
                if hasattr(step_log, key):
                    setattr(step_log, key, value)
            session.commit()
            session.refresh(step_log)
        return step_log


# ============== JSON 导入导出 ==============

def import_from_json(json_path: Path) -> int:
    """从 JSON 文件导入工作流
    
    Returns:
        导入的工作流数量
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 先导入/合并 Webhook 配置（以 name 为唯一键），用于跨机器映射 webhook_id
    webhooks_data = data.get("webhooks", [])
    workflows_data = data.get('workflows', [])
    imported_count = 0
    
    with get_session() as session:
        webhook_name_to_id = {}
        if isinstance(webhooks_data, list) and webhooks_data:
            for wh in webhooks_data:
                if not isinstance(wh, dict):
                    continue
                name = (wh.get("name") or "").strip()
                url = (wh.get("webhook_url") or "").strip()
                if not name or not url:
                    continue
                keyword = (wh.get("keyword") or "").strip()
                desc = (wh.get("description") or "").strip()

                existing = session.query(WebhookConfig).filter(WebhookConfig.name == name).first()
                if existing:
                    # 合并更新：以导入为准（便于跨设备一致）
                    existing.webhook_url = url
                    existing.keyword = keyword or None
                    existing.description = desc or None
                    existing.updated_at = datetime.now()
                    session.flush()
                    webhook_name_to_id[name] = existing.id
                else:
                    item = WebhookConfig(
                        name=name,
                        webhook_url=url,
                        keyword=keyword or None,
                        description=desc or None,
                    )
                    session.add(item)
                    session.flush()
                    webhook_name_to_id[name] = item.id

        for wf_data in workflows_data:
            # 创建工作流
            single_args = wf_data.get('single_script', {}).get('args')
            if isinstance(single_args, list):
                single_args = json.dumps(single_args, ensure_ascii=False)
            workflow = Workflow(
                uid=wf_data.get('id', generate_uid()),
                name=wf_data.get('name', '未命名工作流'),
                chart_theme=wf_data.get('chart_theme', 'default'),
                parallel_enabled=wf_data.get('parallel', {}).get('enabled', False),
                max_workers=wf_data.get('parallel', {}).get('max_workers', 2),
                watch_enabled=wf_data.get('watch', {}).get('enabled', False),
                watch_mode=wf_data.get('watch', {}).get('mode', 'any_change'),
                cooldown_seconds=wf_data.get('watch', {}).get('cooldown_seconds', 8),
                settle_seconds=wf_data.get('watch', {}).get('settle_seconds', 15),
                single_script_enabled=wf_data.get('single_script', {}).get('enabled', False),
                single_script_type=wf_data.get('single_script', {}).get('type', 'python'),
                single_script_path=wf_data.get('single_script', {}).get('path'),
                single_script_args=single_args,
                single_script_cwd=wf_data.get('single_script', {}).get('cwd')
            )
            
            # 设置通知配置
            if 'notify' in wf_data:
                notify = wf_data.get("notify") or {}
                if isinstance(notify, str):
                    try:
                        notify = json.loads(notify)
                    except json.JSONDecodeError:
                        notify = {}
                if not isinstance(notify, dict):
                    notify = {}

                # webhook_id 跨机器不稳定：优先用 webhook_name 映射
                wh_name = (notify.get("webhook_name") or "").strip()
                if wh_name and wh_name in webhook_name_to_id:
                    notify["webhook_id"] = webhook_name_to_id[wh_name]
                else:
                    wh_id = notify.get("webhook_id")
                    if wh_id:
                        exists = session.query(WebhookConfig).filter(WebhookConfig.id == wh_id).first()
                        if not exists:
                            notify["webhook_id"] = None

                workflow.set_notify_config(notify)
            if 'watch' in wf_data:
                folders = wf_data.get('watch', {}).get('folders', [])
                if folders:
                    workflow.set_watch_folders(folders)
            
            session.add(workflow)
            session.flush()

            # 用途阶段（人为归类）
            stages_data = wf_data.get("stages", [])
            stage_uid_set: set[str] = set()
            stage_uid_map: dict[str, str] = {}
            if isinstance(stages_data, list) and stages_data:
                for idx, st in enumerate(stages_data):
                    if not isinstance(st, dict):
                        continue
                    import_uid = (st.get("uid") or "").strip() or generate_uid()
                    st_uid = import_uid
                    st_name = (st.get("name") or "").strip() or f"阶段 {idx + 1}"
                    st_order = int(st.get("order") if st.get("order") is not None else idx)
                    st_color = (st.get("color") or None) or None
                    # 避免 uid 冲突（uid 全局唯一）
                    if session.query(WorkflowStage).filter(WorkflowStage.uid == st_uid).first():
                        st_uid = generate_uid()
                    stage_uid_map[import_uid] = st_uid
                    session.add(
                        WorkflowStage(
                            uid=st_uid,
                            workflow_id=workflow.id,
                            name=st_name,
                            order=st_order,
                            color=st_color,
                        )
                    )
                    stage_uid_set.add(st_uid)
                session.flush()

            default_stage = _ensure_default_stage_in_session(session, workflow.id)
            stage_uid_set.add(default_stage.uid)
            
            # 创建步骤
            for idx, step_data in enumerate(wf_data.get('steps', [])):
                stage_uid_in = (step_data.get("stage_uid") or "").strip()
                stage_uid = stage_uid_map.get(stage_uid_in, stage_uid_in) if stage_uid_in else default_stage.uid
                if stage_uid not in stage_uid_set:
                    stage_uid = default_stage.uid
                step = Step(
                    workflow_id=workflow.id,
                    uid=step_data.get('id', generate_uid()),
                    order=idx,
                    name=step_data.get('name', f'步骤 {idx + 1}'),
                    stage_uid=stage_uid,
                    step_type=step_data.get('step_type', 'python'),
                    script_path=step_data.get('script', ''),
                    cwd=step_data.get('cwd', ''),
                    is_gate=step_data.get('is_gate', False),
                    is_parallel=step_data.get('is_parallel', False),
                    chart_theme=step_data.get('chart_theme', '')
                )
                
                # 设置参数
                args = step_data.get('args', [])
                if args:
                    step.set_args(args)
                
                deps = step_data.get('depends_on', [])
                if deps:
                    step.set_depends_on(deps)
                
                session.add(step)
            
            imported_count += 1
        
        session.commit()
    
    return imported_count


def export_to_json(json_path: Path):
    """导出工作流到 JSON 文件"""
    workflows = list_workflows()
    
    data = {
        "version": 1,
        "webhooks": [],
        "workflows": []
    }
    
    with get_session() as session:
        # Webhook 管理配置：完整备份
        webhooks = session.query(WebhookConfig).order_by(WebhookConfig.name).all()
        data["webhooks"] = [
            {
                "name": wh.name,
                "webhook_url": wh.webhook_url,
                "keyword": wh.keyword or "",
                "description": wh.description or "",
            }
            for wh in webhooks
        ]

        for workflow in workflows:
            notify = workflow.get_notify_config()
            if not isinstance(notify, dict):
                notify = {}
            else:
                notify = dict(notify)
            # 跨机器映射：补充 webhook_name（稳定键）
            wh_id = notify.get("webhook_id")
            if wh_id:
                wh = session.query(WebhookConfig).filter(WebhookConfig.id == wh_id).first()
                if wh:
                    notify["webhook_name"] = wh.name

            wf_data = {
                "id": workflow.uid,
                "name": workflow.name,
                "chart_theme": workflow.chart_theme,
                "parallel": {
                    "enabled": workflow.parallel_enabled,
                    "max_workers": workflow.max_workers
                },
                "notify": notify,
                "watch": {
                    "enabled": workflow.watch_enabled,
                    "mode": workflow.watch_mode,
                    "folders": workflow.get_watch_folders(),
                    "cooldown_seconds": workflow.cooldown_seconds,
                    "settle_seconds": workflow.settle_seconds
                },
                "single_script": {
                    "enabled": workflow.single_script_enabled,
                    "type": workflow.single_script_type,
                    "path": workflow.single_script_path,
                    "args": workflow.single_script_args,
                    "cwd": workflow.single_script_cwd
                },
                "stages": [],
                "steps": []
            }
            
            # 用途阶段
            stages = session.query(WorkflowStage).filter(
                WorkflowStage.workflow_id == workflow.id
            ).order_by(WorkflowStage.order.asc()).all()
            wf_data["stages"] = [
                {
                    "uid": st.uid,
                    "name": st.name,
                    "order": int(st.order or 0),
                    "color": st.color or "",
                }
                for st in stages
            ]

            # 获取步骤
            steps = session.query(Step).filter(
                Step.workflow_id == workflow.id
            ).order_by(Step.order.asc()).all()
            for step in steps:
                step_data = {
                    "id": step.uid,
                    "name": step.name,
                    "stage_uid": step.stage_uid or "",
                    "step_type": step.step_type,
                    "script": step.script_path or "",
                    "args": step.get_args(),
                    "cwd": step.cwd or "",
                    "is_gate": step.is_gate,
                    "is_parallel": step.is_parallel,
                    "depends_on": step.get_depends_on(),
                    "chart_theme": step.chart_theme or ""
                }
                wf_data["steps"].append(step_data)
            
            data["workflows"].append(wf_data)
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============== Webhook CRUD ==============

def list_webhooks() -> List[WebhookConfig]:
    """获取所有 Webhook 配置"""
    with get_session() as session:
        return session.query(WebhookConfig).order_by(WebhookConfig.name).all()


def get_webhook_by_id(webhook_id: int) -> Optional[WebhookConfig]:
    """根据 ID 获取 Webhook"""
    with get_session() as session:
        return session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()


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
        return webhook


def update_webhook(webhook_id: int, **kwargs) -> Optional[WebhookConfig]:
    """更新 Webhook 配置"""
    with get_session() as session:
        webhook = session.query(WebhookConfig).filter(WebhookConfig.id == webhook_id).first()
        if webhook:
            for key, value in kwargs.items():
                if hasattr(webhook, key):
                    setattr(webhook, key, value)
            webhook.updated_at = datetime.now()
            session.commit()
            session.refresh(webhook)
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
