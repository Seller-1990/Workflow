"""Target-specific engine stop: local cancel or durable exact-owner request."""
import logging
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from database_run_ownership import StopState, recover_orphaned_run, request_run_stop

logger = logging.getLogger(__name__)


def force_stop_run(engine, run_history_id):
    import engine as facade

    with engine._lock:
        if engine._running and run_history_id in engine._active_run_ids:
            engine._cancelled = True
            engine._emit_log(f"已发送停止信号给当前运行 (run_history_id={run_history_id})")
            return StopState("acknowledged")
    try:
        state = request_run_stop(run_history_id)
        if state.status == "ownerless" or (state.status == "already_terminal" and state.owner_token is None):
            # Legacy histories have no claim. Keep the existing facade seam and
            # cleanup-before-terminal contract for those rows.
            from database import cancel_pending_step_logs
            return facade._force_cancel_run_record(
                run_history_id,
                get_status=lambda rid: facade._read_run_history_status(
                    rid, session_factory=facade.get_session, run_history_model=facade.RunHistory,
                ),
                cancel_pending_step_logs=cancel_pending_step_logs,
                update_run_history=facade.update_run_history,
                cancelled_status_value=facade.RunStatus.CANCELLED.value,
                now=datetime.now(), log_cb=engine._emit_log, warn_cb=logger.warning,
            )
        if state.status == "orphaned":
            state = recover_orphaned_run(
                run_history_id, expected_run_id=state.run_id,
                expected_owner_token=state.owner_token,
            )
        messages = {
            "requested": "停止请求已持久化，等待所有者确认；尚未停止",
            "acknowledged": "所有者已确认停止请求，正在协作取消；尚未完成",
            "completed": "停止请求已收尾",
            "already_terminal": "运行已是终态，未覆盖原结果",
            "cancelled": "已回收失活或已释放所有者的孤儿运行",
            "unreachable": "无法确认所有者响应；未把运行提前标为已停止",
            "conflict": "运行身份冲突，未停止其他运行",
            "not_found": "运行记录不存在",
        }
        engine._emit_log(f"{messages.get(state.status, state.status)} (run_history_id={run_history_id})")
        return state
    except (SQLAlchemyError, OSError, RuntimeError) as error:
        logger.warning("强制停止运行记录失败: %s", error)
        engine._emit_log(f"强制停止失败: {error}")
        return StopState("unreachable")
