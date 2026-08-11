# -*- coding: utf-8 -*-
"""拆自 database.py（L1 巨型文件治理），会话仍由 database.get_session 提供。

工作流（Workflow）/用途阶段（WorkflowStage）/步骤（Step）CRUD 与最近使用记录；
通过 database.py 门面再导出，调用方无需感知此拆分。
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database_field_guards import (
    STAGE_UPDATE_FIELDS,
    STEP_UPDATE_FIELDS,
    WORKFLOW_UPDATE_FIELDS,
    validate_update_fields as _validate_update_fields,
)
from models import Workflow, WorkflowStage, Step, RecentWorkflow


# ============== Workflow CRUD ==============

def create_workflow(
    name: str,
    description: str = "",
    chart_theme: str = "default",
    parallel_enabled: bool = False,
    max_workers: int = 2
) -> Workflow:
    """创建工作流"""
    from database import get_session, generate_uid, _ensure_default_stage_in_session
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
    from database import get_session
    with get_session() as session:
        return session.query(Workflow).filter(Workflow.uid == uid).first()


def get_workflow_by_id(workflow_id: int) -> Optional[Workflow]:
    """根据 ID 获取工作流"""
    from database import get_session
    with get_session() as session:
        return session.query(Workflow).filter(Workflow.id == workflow_id).first()


def get_workflow_by_name(name: str) -> Optional[Workflow]:
    """根据名称获取工作流（精确匹配）"""
    from database import get_session
    with get_session() as session:
        return session.query(Workflow).filter(Workflow.name == name.strip()).first()


def search_workflows(keyword: str) -> List[Workflow]:
    """根据关键词模糊搜索工作流（名称或UID包含关键词）"""
    from database import get_session
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
    from database import get_session
    with get_session() as session:
        return (
            session.query(Step)
            .filter(Step.workflow_id == workflow_id, Step.name == name.strip())
            .first()
        )


def search_steps(workflow_id: int, keyword: str) -> List["Step"]:
    """根据关键词模糊搜索工作流中的步骤"""
    from database import get_session
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
    from database import get_session
    with get_session() as session:
        return (
            session.query(WorkflowStage)
            .filter(WorkflowStage.workflow_id == workflow_id, WorkflowStage.name == name.strip())
            .first()
        )


def search_stages(workflow_id: int, keyword: str) -> List["WorkflowStage"]:
    """根据关键词模糊搜索工作流中的阶段"""
    from database import get_session
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
    from database import get_session
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
    from database import get_session
    with get_session() as session:
        rows = session.query(Workflow.uid, Workflow.name).all()
        return {uid: name for uid, name in rows}


def list_recent_workflows(limit: int = 10) -> List[str]:
    """获取最近使用的子工作流 UID"""
    from database import get_session
    with get_session() as session:
        items = session.query(RecentWorkflow).order_by(RecentWorkflow.updated_at.desc()).limit(limit).all()
        return [item.workflow_uid for item in items]


def update_recent_workflow(uid: str):
    """更新最近使用的子工作流"""
    from database import get_session
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
    from database import get_session, invalidate_cycle_check_cache
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


def delete_workflow(workflow_id: int) -> bool:
    """删除工作流。

    使用显式批量删除代替 ``session.delete(workflow)``，避免历史记录和
    步骤日志很多时触发 ORM 级联加载大量对象。
    """
    from database import get_session
    from database_workflow_delete import delete_workflow_impl

    return delete_workflow_impl(workflow_id, get_session=get_session)


def copy_workflow(workflow_id: int, new_name: str) -> Optional[Workflow]:
    """复制工作流。

    兼容旧 API；实际实现统一委托给 clone_workflow，确保步骤依赖 UID 会被重映射。
    """
    from database import clone_workflow
    return clone_workflow(workflow_id, new_name)


# ============== Stage CRUD ==============

def list_stages(workflow_id: int) -> List[WorkflowStage]:
    """获取工作流的用途阶段（按 order 排序）"""
    from database import get_session
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
    from database import get_session, generate_uid, _ensure_default_stage_in_session
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
    from database import get_session
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
    from database import get_session
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
    from database import get_session, _ensure_default_stage_in_session
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
    from database import (
        get_session,
        generate_uid,
        invalidate_cycle_check_cache,
        _ensure_default_stage_in_session,
    )
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
    from database import get_session, generate_uid
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
            saved_run_args=source.saved_run_args,
            cwd=source.cwd,
            is_gate=source.is_gate,
            is_parallel=source.is_parallel,
            depends_on=source.depends_on,
            chart_theme=source.chart_theme,
            timeout_seconds=source.timeout_seconds,
            retry_count=source.retry_count,
            skip_on_success=source.skip_on_success,
            output_paths=source.output_paths,
        )
        session.add(new_step)
        session.commit()
        session.refresh(new_step)
        return new_step


def get_steps_by_workflow(workflow_id: int) -> List[Step]:
    """获取工作流的所有步骤"""
    from database import get_session
    with get_session() as session:
        return session.query(Step).filter(
            Step.workflow_id == workflow_id
        ).order_by(Step.order).all()


def update_step(step_id: int, **kwargs) -> Optional[Step]:
    """更新步骤"""
    _validate_update_fields("Step", kwargs, STEP_UPDATE_FIELDS)
    from database import get_session, invalidate_cycle_check_cache
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
    from database import get_session, invalidate_cycle_check_cache
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
    from database import get_session
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


def get_step_by_id(step_id: int):
    """根据 ID 获取单个步骤"""
    from database import get_session
    with get_session() as session:
        return session.query(Step).filter(Step.id == step_id).first()
