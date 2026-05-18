# -*- coding: utf-8 -*-
"""通知子系统：CA2 把 `_send_notification` 从 engine.py 抽离

设计要点：
- 不依赖 QObject，便于 headless CLI / 其它入口直接调用
- 通过 log 回调与上层引擎解耦（日志可写到任意 sink）
- 兼容原行为：所有异常都被吞并降级为 log 输出
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from database import get_webhook_by_id
from notifier import send_workflow_notification

logger = logging.getLogger(__name__)


def send_run_notification(
    workflow,
    run_id: str,
    status: str,
    log_dir: str,
    reason: str,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    *,
    log_cb: Callable[[str], None],
) -> None:
    """根据 workflow.notify_config 发送钉钉通知

    Args:
        workflow: 工作流 ORM 对象（需要 ``get_notify_config()`` 与 ``name`` / ``uid``）
        run_id: 运行编号
        status: success / failure / cancelled
        log_dir: 运行日志目录
        reason: 触发原因（manual / watch / cli / sub_workflow ...）
        start_time / end_time: 运行起止时间，用于计算 duration_seconds
        log_cb: 日志回调，所有反馈走它（解耦 QObject 信号）
    """
    try:
        notify_config = workflow.get_notify_config()
        if not notify_config.get("enabled"):
            return

        webhook_id = notify_config.get("webhook_id")
        if not webhook_id:
            log_cb("通知未配置机器人")
            return

        webhook = get_webhook_by_id(webhook_id)
        if not webhook:
            log_cb(f"未找到机器人配置: {webhook_id}")
            return

        template = notify_config.get(
            "message_template", "{工作流名称} - {状态} - 编号={运行编号}"
        )
        duration = None
        if start_time and end_time:
            duration = (end_time - start_time).total_seconds()

        success, msg = send_workflow_notification(
            webhook_url=webhook.webhook_url,
            keyword=webhook.keyword or "",
            template=template,
            workflow_name=workflow.name,
            workflow_uid=workflow.uid,
            status=status,
            run_id=run_id,
            log_dir=log_dir,
            reason=reason,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
        )

        if success:
            log_cb(f"已发送钉钉通知到【{webhook.name}】")
        else:
            log_cb(f"钉钉通知发送失败: {msg}")
    except Exception as e:
        logger.exception("发送通知出错: %s", e)
        log_cb(f"发送通知出错: {e}")
