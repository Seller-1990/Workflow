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


class BeginRunError(RuntimeError):
    """运行初始化失败，但 RunHistory 已创建且必须由外层收尾。"""

    def __init__(self, context: RunContext):
        super().__init__(f"运行初始化失败 (run_history_id={context.run_history_id})")
        self.context = context


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
    create_run_history_fn=None,
) -> RunContext:
    """创建 RunHistory + log_dir，并把状态切到 running

    把原来 engine._run 中的 3 段调用（create_run_history、log_dir.mkdir、
    update_run_history(status=running, start_time, log_dir)）打包，
    返回上层后续仍然需要的上下文（run_history_id / run_id / log_dir）。
    """
    # 引擎可注入创建入口，在记录对外可见时原子登记其真实 ID。
    create_history = create_run_history_fn or create_run_history
    run_history = create_history(
        workflow_id=workflow.id,
        run_mode=mode_value,
        run_mode_param=run_mode_param,
        reason=reason,
        trace_id=trace_id,
        parent_run_id=parent_run_id,
    )

    log_dir = LOG_DIR / workflow.uid / run_history.run_id
    ctx = RunContext(
        run_history_id=run_history.id,
        run_id=run_history.run_id,
        trace_id=run_history.trace_id,
        parent_run_id=run_history.parent_run_id,
        log_dir=log_dir,
    )
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        update_run_history(
            run_history.id,
            status=running_status_value,
            start_time=start_time,
            log_dir=str(log_dir),
        )
    except Exception as exc:
        raise BeginRunError(ctx) from exc

    return ctx


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
    from database_step_log_creation import step_log_operation
    with step_log_operation(run_history_id, step_id):
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
    from database_step_log_creation import step_log_operation
    with step_log_operation(run_history_id, step_id):
        sl = create_step_log(run_history_id=run_history_id, step_id=step_id, order=order)
    update_step_log(
        sl.id,
        status="skipped",
        start_time=start_time,
        end_time=end_time,
        error_message=note,
    )
    return sl.id


from engine_core.skip_on_success import (
    SkipDecision, build_prev_step_status_map, should_skip_on_success,
    record_skip_on_success, check_skip_on_success,
)
