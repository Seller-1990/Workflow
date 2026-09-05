# -*- coding: utf-8 -*-
"""拆自 database.py（L1 巨型文件治理），会话仍由 database.get_session 提供。

运行历史（RunHistory）与步骤日志（StepLog）CRUD；
通过 database.py 门面再导出，调用方无需感知此拆分。
"""

import logging
import time
from datetime import datetime
from typing import Optional, List

from sqlalchemy import text, func
from sqlalchemy.orm import Session, joinedload

from database_field_guards import (
    RUN_HISTORY_UPDATE_FIELDS,
    STEP_LOG_UPDATE_FIELDS,
    validate_update_fields as _validate_update_fields,
)
from models import RunHistory, StepLog
from run_policy_notes import count_policy_risk_notes

logger = logging.getLogger(__name__)
MAX_ERROR_MESSAGE_LENGTH = 4096


def truncate_error_message(message: object, max_length: int = MAX_ERROR_MESSAGE_LENGTH) -> str | None:
    if message is None:
        return None
    value = str(message)
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."


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
    from database import generate_uid, get_session
    run_id = generate_uid()
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
        # F-01: fallback 复制对象移除——原为 refresh 失败时返回"已知字段"的兜底；
        # expire_on_commit=False 下对象属性在 commit 后仍有效，refresh 只是补
        # DEFAULT/ON UPDATE 列。refresh 失败时对象已含全部入参字段，直接返回即可
        # （id 由 flush 时自增填充）。仍保留 refresh 本身：start_time 等服务端列。
        try:
            session.refresh(run_history)
        except Exception as exc:
            logger.warning("RunHistory 已提交但刷新失败（返回提交时对象）: id=%s, error=%s", run_history.id, exc)
            try:
                session.rollback()
            except Exception:
                pass
        return run_history


def get_run_histories_by_workflow(
    workflow_id: int,
    limit: int = 20,
    offset: int = 0,
) -> List[RunHistory]:
    """获取工作流的运行历史"""
    from database import get_session
    with get_session() as session:
        query = session.query(RunHistory).filter(RunHistory.workflow_id == workflow_id)
        offset_value = max(0, int(offset or 0))
        limit_value = max(1, int(limit or 1))
        results = query.order_by(RunHistory.id.desc()).offset(offset_value).limit(limit_value).all()
        # F-01: get_session 现于块退出时 close，identity map 随 session 关闭清空，
        # PF2 手工 expire 循环不再必要（且 close 后 expire 会产生 detached+expired
        # 对象，反成隐患），移除。
        return results


def get_latest_run_history(
    workflow_id: int,
    include_statuses: Optional[List[str]] = None,
    exclude_statuses: Optional[List[str]] = None,
    only_finished: bool = False,
    exclude_run_history_id: Optional[int] = None,
) -> Optional[RunHistory]:
    """获取最新的运行历史"""
    from database import get_session
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
        return query.order_by(RunHistory.id.desc()).first()


def update_run_history(run_history_id: int, **kwargs) -> Optional[RunHistory]:
    """更新运行历史

    Args:
        _condition_status: 可选条件——仅当当前 status 等于该值时才更新。
            用于 force_stop 竞态保护：避免覆盖正常 finalization 已写入的终态。
            不匹配时返回 None（表示未修改）。
    """
    condition_status = kwargs.pop("_condition_status", None)
    _validate_update_fields("RunHistory", kwargs, RUN_HISTORY_UPDATE_FIELDS)
    from database import get_session
    with get_session() as session:
        query = session.query(RunHistory).filter(RunHistory.id == run_history_id)
        if condition_status is not None:
            query = query.filter(RunHistory.status == condition_status)
        run_history = query.first()
        if run_history:
            for key, value in kwargs.items():
                setattr(run_history, key, value)
            session.commit()
            session.refresh(run_history)
        return run_history


# ============== StepLog CRUD ==============


def clear_run_histories(workflow_id: int) -> int:
    """清除指定工作流的所有运行历史（优化：使用子查询批量删除，避免大 IN 子句）

    Returns:
        删除的记录数
    """
    from database import get_session
    with get_session() as session:
        # 使用子查询避免将全部 ID 加载到 Python 侧
        history_id_subquery = (
            session.query(RunHistory.id)
            .filter(RunHistory.workflow_id == workflow_id)
            .subquery()
        )

        # 批量删除关联的步骤日志
        session.query(StepLog).filter(
            StepLog.run_history_id.in_(session.query(history_id_subquery.c.id))
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
    order: int = 0,
    error_message: str | None = None,
) -> StepLog:
    """创建步骤日志"""
    last_error = None
    safe_error_message = truncate_error_message(error_message)
    from database import get_session
    for attempt in range(3):
        with get_session() as session:
            step_log = StepLog(
                run_history_id=run_history_id,
                step_id=step_id,
                order=order,
                status="pending",
                error_message=safe_error_message,
            )
            session.add(step_log)
            try:
                session.flush()
                session.commit()
            except Exception as e:
                session.rollback()
                last_error = e
                if attempt < 2:
                    time.sleep(0.1 * (attempt + 1))
                continue
            # F-01: fallback 复制对象移除（同 create_run_history）——refresh 失败
            # 时直接返回已含全部入参字段的对象。
            try:
                session.refresh(step_log)
            except Exception as exc:
                logger.warning("StepLog 已提交但刷新失败（返回提交时对象）: id=%s, error=%s", step_log.id, exc)
                try:
                    session.rollback()
                except Exception:
                    pass
            return step_log
    raise last_error


def get_step_logs_by_run(run_history_id: int) -> List[StepLog]:
    """获取运行的所有步骤日志"""
    from database import get_session
    with get_session() as session:
        return session.query(StepLog).options(joinedload(StepLog.step)).filter(
            StepLog.run_history_id == run_history_id
        ).order_by(StepLog.order).all()


def get_recent_step_logs_for_step(workflow_id: int, step_id: int, limit: int = 20) -> List[StepLog]:
    """P-11: 一次查询拿到指定 step 在最近 N 个 run 中的所有 StepLog（按 run 创建时间倒序）。

    替代"循环 RunHistory → 每条查 StepLog"的 N+1 模式，给 UI 找最近一次日志路径用。
    """
    from database import get_session
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

    base_statuses = [
        "success", "failure", "skipped", "cancelled", "running", "pending",
        "manual_required", "background_risk", "orphan_risk",
    ]
    summary = {
        int(run_history_id): {status: 0 for status in base_statuses}
        for run_history_id in run_history_ids
    }

    from database import get_session
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

        risk_rows = session.query(
            StepLog.run_history_id,
            StepLog.error_message,
        ).filter(
            StepLog.run_history_id.in_(run_history_ids),
            StepLog.error_message.isnot(None),
        ).all()

    for run_history_id, status, count in rows:
        bucket = summary.setdefault(int(run_history_id), {key: 0 for key in base_statuses})
        status_key = str(status or "pending")
        bucket.setdefault(status_key, 0)
        bucket[status_key] = int(count or 0)

    for run_history_id, error_message in risk_rows:
        bucket = summary.setdefault(int(run_history_id), {key: 0 for key in base_statuses})
        for key, increment in count_policy_risk_notes(error_message).items():
            bucket[key] = int(bucket.get(key, 0)) + increment

    return summary


def cancel_pending_step_logs(run_history_id: int, error_message: str = "用户强制停止") -> int:
    """R4-#9: 批量把指定 run 下所有 pending/running 的 step_logs 改为 cancelled。

    使用单次 UPDATE 替代 N 次 update_step_log，避免 N+1 commit。
    返回被改动的行数。
    """
    return finish_unfinished_step_logs(run_history_id, "cancelled", error_message)


def finish_unfinished_step_logs(
    run_history_id: int,
    status: str,
    error_message: str = "未完成步骤被清理",
) -> int:
    """批量把指定 run 下所有 pending/running 的 step_logs 收敛到终态。"""
    now = datetime.now()
    safe_error_message = truncate_error_message(error_message)
    try:
        from database import get_session
        with get_session() as session:
            affected = (
                session.query(StepLog)
                .filter(
                    StepLog.run_history_id == run_history_id,
                    StepLog.status.in_(("pending", "running")),
                )
                .update(
                    {
                        StepLog.status: status,
                        StepLog.end_time: now,
                        StepLog.error_message: safe_error_message,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return int(affected or 0)
    except Exception as e:
        logger.warning("批量收敛 step_logs 失败: %s", e)
        return 0


def update_step_log(step_log_id: int, **kwargs) -> Optional[StepLog]:
    """更新步骤日志

    R4-#4/F-12: 终态写入不做 WAL checkpoint——WAL 模式下 commit 后任何连接
    （含跨进程）立即可见；-wal 体积由 SQLite 默认 wal_autocheckpoint（1000 页）承担。
    """
    _validate_update_fields("StepLog", kwargs, STEP_LOG_UPDATE_FIELDS)
    if "error_message" in kwargs:
        kwargs["error_message"] = truncate_error_message(kwargs.get("error_message"))
    from database import get_session
    with get_session() as session:
        step_log = session.query(StepLog).filter(StepLog.id == step_log_id).first()
        if step_log:
            for key, value in kwargs.items():
                setattr(step_log, key, value)
            session.commit()
            session.refresh(step_log)
        return step_log
