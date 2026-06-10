# -*- coding: utf-8 -*-
"""通知子系统：CA2 把 `_send_notification` 从 engine.py 抽离

设计要点：
- 不依赖 QObject，便于 headless CLI / 其它入口直接调用
- 通过 log 回调与上层引擎解耦（日志可写到任意 sink）
- 兼容原行为：所有异常都被吞并降级为 log 输出
- ROI-1: 通知结果回写 run_histories.notify_status
  （sent / failed: 摘要 / skipped: 原因），回写失败绝不影响通知流程
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from database import get_webhook_by_id
from notifier import resolve_workflow_notification_target, send_workflow_notification

logger = logging.getLogger(__name__)

# notify_status 列为 String(255)，回写前统一截断，避免超长失败摘要写库报错
_NOTIFY_STATUS_MAX_LEN = 250


def _resolve_run_history_id(run_id: str) -> Optional[int]:
    """按 run_id 反查 run_histories.id（兼容 engine.py 未传 run_history_id 的旧调用）"""
    # 延迟 import：与 codebase 惯例一致，避免模块导入期产生额外依赖
    from database import get_session
    from models import RunHistory

    with get_session() as session:
        row = (
            session.query(RunHistory.id)
            .filter(RunHistory.run_id == run_id)
            .order_by(RunHistory.id.desc())
            .first()
        )
        return int(row[0]) if row else None


def _record_notify_status(run_history_id: Optional[int], run_id: str, value: str) -> None:
    """把通知结果回写到 run_histories.notify_status

    run_history_id 缺省时按 run_id 反查。回写失败绝不能打断通知线程 /
    运行收尾，因此整体兜底吞掉异常，只留 warning 日志
    （与模块头部「异常降级为日志」的设计一致）。
    """
    try:
        from database import update_run_history

        if run_history_id is None:
            run_history_id = _resolve_run_history_id(run_id)
        if run_history_id is None:
            logger.warning("未找到 run_id=%s 对应的运行记录，跳过通知状态回写", run_id)
            return
        update_run_history(run_history_id, notify_status=str(value)[:_NOTIFY_STATUS_MAX_LEN])
    except Exception as e:  # 回写失败只记日志，不能影响通知主流程
        logger.warning("通知状态回写失败 (run_id=%s): %s", run_id, e)


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
    run_history_id: Optional[int] = None,
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
        run_history_id: 运行记录主键，用于回写 notify_status；
            缺省（None）时按 run_id 反查，保持 engine.py 旧调用兼容
    """
    try:
        # 薄前置检查：resolve_workflow_notification_target 会把「未启用 /
        # 未绑定机器人 / 机器人配置缺失」折叠成同一个 None，这里先区分前
        # 两种早退场景，保持原有 log_cb 提示与回写语义不漂移。
        notify_config = workflow.get_notify_config()
        if not isinstance(notify_config, dict) or not notify_config.get("enabled"):
            _record_notify_status(run_history_id, run_id, "skipped: 未启用")
            return

        webhook_id = notify_config.get("webhook_id")
        if not webhook_id:
            log_cb("通知未配置机器人")
            _record_notify_status(run_history_id, run_id, "skipped: 未配置机器人")
            return

        # L2 收尾：webhook 查询与模板提取统一走 notifier 的规范实现，
        # 默认模板权威定义见 notifier.DEFAULT_NOTIFY_MESSAGE_TEMPLATE，
        # 即 "{工作流名称} - {状态} - 编号={运行编号}"，此处不再手写字面量。
        target = resolve_workflow_notification_target(workflow, get_webhook_by_id)
        if target is None:
            # 前置检查已排除未启用 / 未绑定，此处只剩机器人配置缺失一种可能
            log_cb(f"未找到机器人配置: {webhook_id}")
            _record_notify_status(run_history_id, run_id, f"failed: 未找到机器人配置: {webhook_id}")
            return

        webhook, template = target
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
            _record_notify_status(run_history_id, run_id, "sent")
        else:
            log_cb(f"钉钉通知发送失败: {msg}")
            _record_notify_status(run_history_id, run_id, f"failed: {msg}")
    except Exception as e:
        logger.exception("发送通知出错: %s", e)
        log_cb(f"发送通知出错: {e}")
        _record_notify_status(run_history_id, run_id, f"failed: {e}")
