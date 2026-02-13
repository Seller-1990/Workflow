# -*- coding: utf-8 -*-
"""钉钉消息通知模块"""

import requests
from typing import Optional
from datetime import datetime


# 可用的模板变量
TEMPLATE_VARIABLES = {
    "{工作流名称}": "workflow_name",
    "{工作流编号}": "workflow_uid",
    "{状态}": "status",
    "{运行编号}": "run_id",
    "{日志目录}": "log_dir",
    "{原因}": "reason",
    "{开始时间}": "start_time",
    "{结束时间}": "end_time",
    "{耗时}": "duration",
    "{失败摘要}": "failure_summary",
}

# 状态显示映射
STATUS_MAP = {
    "success": "✅ 成功",
    "failure": "❌ 失败",
    "cancelled": "⚠️ 已取消",
    "running": "🔄 运行中",
    "pending": "⏳ 等待中",
}


def format_message(
    template: str,
    workflow_name: str = "",
    workflow_uid: str = "",
    status: str = "",
    run_id: str = "",
    log_dir: str = "",
    reason: str = "",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    duration_seconds: Optional[float] = None,
    failure_summary: str = "",
) -> str:
    """格式化消息模板
    
    Args:
        template: 消息模板
        其他参数: 模板变量值
    
    Returns:
        格式化后的消息
    """
    message = template
    
    # 替换变量
    message = message.replace("{工作流名称}", workflow_name or "")
    message = message.replace("{工作流编号}", workflow_uid or "")
    message = message.replace("{状态}", STATUS_MAP.get(status, status))
    message = message.replace("{运行编号}", run_id or "")
    message = message.replace("{日志目录}", log_dir or "")
    message = message.replace("{原因}", reason or "手动触发")
    
    # 时间相关
    if start_time:
        message = message.replace("{开始时间}", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    else:
        message = message.replace("{开始时间}", "")
    
    if end_time:
        message = message.replace("{结束时间}", end_time.strftime("%Y-%m-%d %H:%M:%S"))
    else:
        message = message.replace("{结束时间}", "")
    
    if duration_seconds is not None:
        if duration_seconds < 60:
            duration_str = f"{duration_seconds:.1f}秒"
        else:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            duration_str = f"{minutes}分{seconds}秒"
        message = message.replace("{耗时}", duration_str)
    else:
        message = message.replace("{耗时}", "")
    
    # 失败摘要
    message = message.replace("{失败摘要}", failure_summary or "")
    
    return message


def send_dingtalk_message(
    webhook_url: str,
    message: str,
    keyword: str = "",
    timeout: int = 10
) -> tuple[bool, str]:
    """发送钉钉消息
    
    Args:
        webhook_url: 钉钉机器人 Webhook URL
        message: 消息内容
        keyword: 安全设置关键字（会自动添加到消息中）
        timeout: 超时时间（秒）
    
    Returns:
        (是否成功, 错误信息或响应)
    """
    if not webhook_url:
        return False, "Webhook URL 为空"
    
    # 如果有关键字，添加到消息开头
    if keyword and keyword not in message:
        message = f"【{keyword}】{message}"
    
    payload = {
        "msgtype": "text",
        "text": {
            "content": message
        }
    }
    
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=timeout,
            headers={"Content-Type": "application/json"}
        )
        
        result = response.json()
        
        if result.get("errcode") == 0:
            return True, "发送成功"
        else:
            return False, f"发送失败: {result.get('errmsg', '未知错误')}"
    
    except requests.exceptions.Timeout:
        return False, "请求超时"
    except requests.exceptions.RequestException as e:
        return False, f"请求错误: {str(e)}"
    except Exception as e:
        return False, f"未知错误: {str(e)}"


def send_workflow_notification(
    webhook_url: str,
    keyword: str,
    template: str,
    workflow_name: str,
    workflow_uid: str,
    status: str,
    run_id: str,
    log_dir: str = "",
    reason: str = "manual",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    duration_seconds: Optional[float] = None,
    failure_summary: str = "",
) -> tuple[bool, str]:
    """发送工作流通知
    
    封装了模板格式化和消息发送
    """
    message = format_message(
        template=template,
        workflow_name=workflow_name,
        workflow_uid=workflow_uid,
        status=status,
        run_id=run_id,
        log_dir=log_dir,
        reason=reason,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration_seconds,
        failure_summary=failure_summary,
    )
    
    return send_dingtalk_message(webhook_url, message, keyword)


def get_template_variables_help() -> str:
    """获取模板变量帮助文本"""
    return "可用变量：{工作流名称} {状态} {运行编号} {日志目录} {原因} {开始时间} {耗时} {失败摘要}"
