# -*- coding: utf-8 -*-
"""运行生命周期：CA2 把 RunHistory / StepLog 的创建 + 状态切换从 engine.py 抽离

设计要点：
- 不依赖 QObject；UI 信号 / 锁 等仍由 engine.py 负责
- 提供"DB 落库 + log_dir 准备"的小步骤组合接口，避免 engine.py 散落 3 段同样的 update_run_history
- 错误路径返回 None / 抛 ConfigurationError，由 engine.py 决定如何反馈
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import LOG_DIR
from database import (
    cancel_pending_step_logs,
    create_run_history,
    update_run_history,
    create_step_log,
    update_step_log,
    get_latest_run_history,
    get_step_logs_by_run,
)
from database_runs import finish_unfinished_step_logs
from engine_core.run_finalization import finalize_run_record

logger = logging.getLogger(__name__)


def _log_finalize_warning(template: str, value: object) -> None:
    if isinstance(value, tuple):
        logger.warning(template, *value)
    else:
        logger.warning(template, value)


@dataclass
class RunContext:
    """开始一次运行后返回的关键上下文"""
    run_history_id: int
    run_id: str
    trace_id: Optional[str]
    parent_run_id: Optional[str]
    log_dir: Path


def begin_run(
    *,
    workflow,
    mode_value: str,
    run_mode_param: Optional[str],
    reason: str,
    trace_id: Optional[str],
    parent_run_id: Optional[str],
    start_time: datetime,
    running_status_value: str,
) -> RunContext:
    """创建 RunHistory + log_dir，并把状态切到 running

    把原来 engine._run 中的 3 段调用（create_run_history、log_dir.mkdir、
    update_run_history(status=running, start_time, log_dir)）打包，
    返回上层后续仍然需要的上下文（run_history_id / run_id / log_dir）。
    """
    run_history = create_run_history(
        workflow_id=workflow.id,
        run_mode=mode_value,
        run_mode_param=run_mode_param,
        reason=reason,
        trace_id=trace_id,
        parent_run_id=parent_run_id,
    )

    log_dir = LOG_DIR / workflow.uid / run_history.run_id
    log_dir.mkdir(parents=True, exist_ok=True)

    update_run_history(
        run_history.id,
        status=running_status_value,
        start_time=start_time,
        log_dir=str(log_dir),
    )

    return RunContext(
        run_history_id=run_history.id,
        run_id=run_history.run_id,
        trace_id=run_history.trace_id,
        parent_run_id=run_history.parent_run_id,
        log_dir=log_dir,
    )


def finalize_run(
    run_history_id: int,
    *,
    status_value: str,
    end_time: datetime,
) -> bool:
    """落库一次运行的最终状态。失败不抛出，返回 bool 给上层用于日志降级。
    """
    return finalize_run_record(
        run_history_id,
        status_value=status_value,
        end_time=end_time,
        update_run_history=update_run_history,
        finish_unfinished_step_logs=finish_unfinished_step_logs,
        cancel_pending_step_logs=cancel_pending_step_logs,
        warn_cb=_log_finalize_warning,
    )


def mark_step_running(step_log_id: int) -> None:
    """步骤进入 running"""
    update_step_log(step_log_id, status="running", start_time=datetime.now())


def create_running_step_log(*, run_history_id: int, step_id: int, order: int) -> int:
    """创建并立刻置为 running 的 StepLog，返回 step_log.id

    P-14: order 必填——避免 caller 漏传导致 StepLog.order 落 0 污染历史排序。
    """
    sl = create_step_log(run_history_id=run_history_id, step_id=step_id, order=order)
    mark_step_running(sl.id)
    return sl.id


def create_skipped_step_log(
    *,
    run_history_id: int,
    step_id: int,
    start_time: datetime,
    end_time: datetime,
    order: int,
    note: Optional[str] = None,
) -> int:
    """创建"已跳过"的 StepLog（用于 skip_on_success），返回 step_log.id

    P-14: order 必填——避免 caller 漏传导致 StepLog.order 落 0 污染历史排序。
    """
    sl = create_step_log(run_history_id=run_history_id, step_id=step_id, order=order)
    update_step_log(
        sl.id,
        status="skipped",
        start_time=start_time,
        end_time=end_time,
        error_message=note,
    )
    return sl.id


# ============== Skip-on-success 决策 ==============

@dataclass
class SkipDecision:
    """``check_skip_on_success`` 命中时返回；调用方据此构造 StepResult / 发信号"""
    step_log_id: int
    start_time: datetime
    end_time: datetime
    note: str  # 默认 "已跳过（上次成功）"


def build_prev_step_status_map(
    workflow_id: int,
    *,
    exclude_run_history_id: Optional[int] = None,
    running_status_value: str = "running",
    pending_status_value: str = "pending",
) -> dict:
    """P-3: 一次性预取该工作流"上一次完结运行"中每个步骤的状态。

    返回 {step_id: status_str}，无最近完结运行时返回 {}。
    供 ``should_skip_on_success(..., prev_step_status_map=...)`` 跳过 N+1 查询。
    """
    latest = get_latest_run_history(
        workflow_id,
        exclude_statuses=[running_status_value, pending_status_value],
        only_finished=True,
        exclude_run_history_id=exclude_run_history_id,
    )
    if not latest:
        return {}
    logs = get_step_logs_by_run(latest.id) or []
    return {pl.step_id: pl.status for pl in logs}


def should_skip_on_success(
    *,
    step,
    run_history_id: int,
    running_status_value: str = "running",
    pending_status_value: str = "pending",
    prev_step_status_map: Optional[dict] = None,
) -> bool:
    """纯检查：判断本步骤是否应跳过（不写任何 DB）。

    #7: 把"检查"与"落库"拆开，让 engine 能在 emit step_started 之后再写 StepLog，
        避免任何 step_started 监听器同步查 DB 时看到 status=skipped 的语义漂移。
    P-3: 优先使用预取的 ``prev_step_status_map`` 跳过 N+1 查询。
    """
    if not getattr(step, "skip_on_success", False):
        return False

    # 预取路径：O(1) 查 map
    if prev_step_status_map is not None:
        return prev_step_status_map.get(step.id) == "success"

    # 回退路径：原 2 次 DB 查询（向后兼容）
    latest = get_latest_run_history(
        step.workflow_id,
        exclude_statuses=[running_status_value, pending_status_value],
        only_finished=True,
        exclude_run_history_id=run_history_id,
    )
    if not latest:
        return False

    prev_logs = get_step_logs_by_run(latest.id)
    for pl in prev_logs:
        if pl.step_id == step.id and pl.status == "success":
            return True
    return False


def record_skip_on_success(
    *,
    step,
    run_history_id: int,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    note: str = "已跳过（上次成功）",
) -> SkipDecision:
    """落库一条 skipped StepLog 并返回 SkipDecision。

    #7: caller 通常先发 step_started 信号，再调本函数写库，再发 step_finished。
    """
    now = datetime.now()
    start_time = start_time or now
    end_time = end_time or now
    step_log_id = create_skipped_step_log(
        run_history_id=run_history_id,
        step_id=step.id,
        start_time=start_time,
        end_time=end_time,
        note=note,
        order=getattr(step, "order", 0),
    )
    return SkipDecision(
        step_log_id=step_log_id,
        start_time=start_time,
        end_time=end_time,
        note=note,
    )


def check_skip_on_success(
    *,
    step,
    run_history_id: int,
    running_status_value: str = "running",
    pending_status_value: str = "pending",
) -> Optional[SkipDecision]:
    """旧组合接口：检查 + 落库一步到位。

    保留以向后兼容；新代码建议用 should_skip_on_success + record_skip_on_success 配合
    在中间插入 step_started 信号。
    """
    if not should_skip_on_success(
        step=step,
        run_history_id=run_history_id,
        running_status_value=running_status_value,
        pending_status_value=pending_status_value,
    ):
        return None
    return record_skip_on_success(step=step, run_history_id=run_history_id)
