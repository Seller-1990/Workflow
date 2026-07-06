# -*- coding: utf-8 -*-
"""CLI notification delivery helpers."""

from __future__ import annotations

from datetime import datetime


def send_cli_notification(
    *,
    workflow,
    success: bool,
    notify_on_complete: bool,
    notify_on_error: bool,
    cancelled: bool = False,
    error_messages: list[dict] | None = None,
    last_run_id: str | None = None,
    last_start_time: datetime | None = None,
    last_end_time: datetime | None = None,
    last_duration_seconds: float | None = None,
    print_func=print,
) -> None:
    """Send the CLI-controlled workflow notification when policy allows it."""
    from database import get_webhook_by_id
    from notifier import resolve_workflow_notification_target, send_workflow_notification

    status = _resolve_notification_status(
        success=success,
        cancelled=cancelled,
        notify_on_complete=notify_on_complete,
        notify_on_error=notify_on_error,
    )
    if status is None:
        return

    target = resolve_workflow_notification_target(workflow, get_webhook_by_id)
    if target is None:
        return
    webhook, template = target

    start_time = last_start_time or datetime.now()
    end_time = last_end_time or datetime.now()
    duration_seconds = last_duration_seconds
    if duration_seconds is None:
        duration_seconds = max(0.0, (end_time - start_time).total_seconds())

    success_send, msg = send_workflow_notification(
        webhook_url=webhook.webhook_url,
        keyword=webhook.keyword or "",
        template=template,
        workflow_name=workflow.name,
        workflow_uid=workflow.uid,
        status=status,
        run_id=last_run_id or ("cli_" + datetime.now().strftime("%Y%m%d_%H%M%S")),
        log_dir="",
        reason="cli",
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration_seconds,
        failure_summary=_format_error_summary(error_messages or []),
    )

    if success_send:
        print_func(f"[通知] 已发送运行状态通知到【{webhook.name}】")
    else:
        print_func(f"[通知] 发送失败: {msg}")


def _resolve_notification_status(
    *,
    success: bool,
    cancelled: bool,
    notify_on_complete: bool,
    notify_on_error: bool,
) -> str | None:
    if cancelled and notify_on_complete:
        return "cancelled"
    if not success and notify_on_error:
        return "failure"
    if success and notify_on_complete:
        return "success"
    return None


def _format_error_summary(error_messages: list[dict]) -> str:
    if not error_messages:
        return ""
    return "\n".join(
        f"{item.get('step_name', '未知步骤')}: {item.get('error_message', '')}"
        for item in error_messages[:3]
    )
