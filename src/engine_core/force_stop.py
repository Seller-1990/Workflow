# -*- coding: utf-8 -*-
"""运行历史强制取消的落库逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

TERMINAL_STATUSES = {"success", "failure", "cancelled"}


@dataclass(frozen=True)
class ForceStopResult:
    status: str
    existing_status: str | None = None
    orphan_steps_cleaned: int = 0


def read_run_history_status(run_history_id: int, *, session_factory, run_history_model) -> str | None:
    """读取 run_history 当前状态。"""
    with session_factory() as session:
        row = (
            session.query(run_history_model.status)
            .filter(run_history_model.id == run_history_id)
            .first()
        )
        return row[0] if row else None


def force_cancel_run_record(
    run_history_id: int,
    *,
    get_status: Callable[[int], str | None],
    cancel_pending_step_logs: Callable[[int, str], int],
    update_run_history: Callable[..., object],
    cancelled_status_value: str,
    now: datetime | None = None,
    log_cb: Callable[[str], None] | None = None,
    warn_cb: Callable[[str, object], None] | None = None,
) -> ForceStopResult:
    """把孤儿运行记录标记为 cancelled，并清理未完成步骤。"""
    existing_status = _safe_get_status(run_history_id, get_status, warn_cb)

    if existing_status in TERMINAL_STATUSES:
        _log(
            log_cb,
            f"运行 {run_history_id} 已是终态 {existing_status}，跳过强制取消",
        )
        affected = _safe_cancel_pending_steps(
            run_history_id,
            "父运行已终态，孤儿步骤被清理",
            cancel_pending_step_logs,
            warn_cb,
            "批量清理孤儿步骤失败: %s",
        )
        if affected:
            _log(log_cb, f"清理 {affected} 个孤儿步骤（run_history_id={run_history_id}）")
        return ForceStopResult(
            status="already_terminal",
            existing_status=existing_status,
            orphan_steps_cleaned=affected,
        )

    _safe_cancel_pending_steps(
        run_history_id,
        "用户强制停止",
        cancel_pending_step_logs,
        warn_cb,
        "批量取消 step_logs 失败: %s",
    )
    update_run_history(
        run_history_id,
        status=cancelled_status_value,
        end_time=now or datetime.now(),
    )
    _log(log_cb, f"已强制停止运行记录 (run_history_id={run_history_id})")
    return ForceStopResult(status="cancelled", existing_status=existing_status)


def _safe_get_status(
    run_history_id: int,
    get_status: Callable[[int], str | None],
    warn_cb: Callable[[str, object], None] | None,
) -> str | None:
    try:
        return get_status(run_history_id)
    except Exception as exc:
        _warn(warn_cb, "读取 run_history 状态失败: %s", exc)
        return None


def _safe_cancel_pending_steps(
    run_history_id: int,
    message: str,
    cancel_pending_step_logs: Callable[[int, str], int],
    warn_cb: Callable[[str, object], None] | None,
    warning_template: str,
) -> int:
    try:
        return int(cancel_pending_step_logs(run_history_id, message) or 0)
    except Exception as exc:
        _warn(warn_cb, warning_template, exc)
        return 0


def _log(log_cb: Callable[[str], None] | None, message: str) -> None:
    if log_cb:
        log_cb(message)


def _warn(warn_cb: Callable[[str, object], None] | None, template: str, exc: object) -> None:
    if warn_cb:
        warn_cb(template, exc)
