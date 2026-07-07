# -*- coding: utf-8 -*-
"""RunHistory / StepLog finalization consistency helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)

try:
    from sqlalchemy.exc import SQLAlchemyError
except ImportError:
    class SQLAlchemyError(RuntimeError):
        """Fallback used when tests import this pure helper without SQLAlchemy."""


FINALIZATION_ERRORS = (RuntimeError, OSError, SQLAlchemyError)


def finalize_run_record(
    run_history_id: int,
    *,
    status_value: str,
    end_time: datetime,
    update_run_history: Callable[..., object],
    finish_unfinished_step_logs: Callable[[int, str, str], int] | None = None,
    cancel_pending_step_logs: Callable[[int, str], int] | None = None,
    cancelled_status_value: str = "cancelled",
    cancel_step_message: str = "运行已取消，未完成步骤被清理",
    warn_cb: Callable[[str, object], None] | None = None,
) -> bool:
    """Finalize a run while keeping unfinished StepLog rows consistent.

    Terminal runs must clean pending/running step logs before writing the run
    terminal status. That ordering avoids observers seeing a terminal run with
    still-running steps in another session.
    """
    cleanup_status, cleanup_message = _unfinished_step_cleanup(
        status_value,
        cancelled_status_value=cancelled_status_value,
        cancel_step_message=cancel_step_message,
    )
    if cleanup_status and (finish_unfinished_step_logs is not None or cancel_pending_step_logs is not None):
        try:
            if finish_unfinished_step_logs is not None:
                finish_unfinished_step_logs(run_history_id, cleanup_status, cleanup_message)
            else:
                cancel_pending_step_logs(run_history_id, cleanup_message)
        except FINALIZATION_ERRORS as exc:
            _warn(warn_cb, "批量收敛未完成 step_logs 失败: %s", exc)

    try:
        kwargs = {"status": status_value, "end_time": end_time}
        update_run_history(run_history_id, **kwargs)
        return True
    except FINALIZATION_ERRORS as exc:
        _warn(warn_cb, "更新运行历史失败: run_history_id=%s, %s", (run_history_id, exc))
        return False


def _unfinished_step_cleanup(
    status_value: str,
    *,
    cancelled_status_value: str,
    cancel_step_message: str,
) -> tuple[str | None, str]:
    if status_value == cancelled_status_value:
        return "cancelled", cancel_step_message
    if status_value == "failure":
        return "failure", "运行失败，未完成步骤被清理"
    if status_value == "success":
        return "skipped", "运行已完成，未执行步骤被清理"
    return None, ""


def _warn(warn_cb: Callable[[str, object], None] | None, template: str, exc: object) -> None:
    if warn_cb:
        warn_cb(template, exc)
    else:
        if isinstance(exc, tuple):
            logger.warning(template, *exc)
        else:
            logger.warning(template, exc)
