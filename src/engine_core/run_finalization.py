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


FINALIZATION_ERRORS = (RuntimeError, ValueError, TypeError, OSError, SQLAlchemyError)


def finalize_run_record(
    run_history_id: int,
    *,
    status_value: str,
    end_time: datetime,
    update_run_history: Callable[..., object],
    cancel_pending_step_logs: Callable[[int, str], int] | None = None,
    cancelled_status_value: str = "cancelled",
    error_message: str | None = None,
    cancel_step_message: str = "运行已取消，未完成步骤被清理",
    warn_cb: Callable[[str, object], None] | None = None,
) -> bool:
    """Finalize a run while keeping unfinished StepLog rows consistent.

    Cancellation must clean pending/running step logs before writing the run
    terminal status. That ordering avoids observers seeing a cancelled run with
    still-running steps in another session.
    """
    if status_value == cancelled_status_value and cancel_pending_step_logs is not None:
        try:
            cancel_pending_step_logs(run_history_id, cancel_step_message)
        except FINALIZATION_ERRORS as exc:
            _warn(warn_cb, "批量取消未完成 step_logs 失败: %s", exc)

    try:
        kwargs = {"status": status_value, "end_time": end_time}
        if error_message is not None:
            safe_msg = str(error_message)
            if len(safe_msg) > 4096:
                safe_msg = safe_msg[:4093] + "..."
            kwargs["error_message"] = safe_msg
        update_run_history(run_history_id, **kwargs)
        return True
    except FINALIZATION_ERRORS as exc:
        _warn(warn_cb, "更新运行历史失败: run_history_id=%s, %s", (run_history_id, exc))
        return False


def _warn(warn_cb: Callable[[str, object], None] | None, template: str, exc: object) -> None:
    if warn_cb:
        warn_cb(template, exc)
    else:
        if isinstance(exc, tuple):
            logger.warning(template, *exc)
        else:
            logger.warning(template, exc)
