# -*- coding: utf-8 -*-
"""钉钉消息通知模块"""

try:
    import requests
except ImportError:
    requests = None
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
    # 构建变量映射
    mapping = {
        "工作流名称": workflow_name or "",
        "工作流编号": workflow_uid or "",
        "状态": STATUS_MAP.get(status, status),
        "运行编号": run_id or "",
        "日志目录": log_dir or "",
        "原因": reason or "手动触发",
    }
    
    # 时间相关
    if start_time:
        mapping["开始时间"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        mapping["开始时间"] = ""
    
    if end_time:
        mapping["结束时间"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        mapping["结束时间"] = ""
    
    if duration_seconds is not None:
        if duration_seconds < 60:
            duration_str = f"{duration_seconds:.1f}秒"
        else:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            duration_str = f"{minutes}分{seconds}秒"
        mapping["耗时"] = duration_str
    else:
        mapping["耗时"] = ""
    
    # 失败摘要
    mapping["失败摘要"] = failure_summary or ""
    
    # 直接进行变量替换（不使用 string.Template，因为它不支持中文变量名）
    # 支持两种模板格式：{变量名} 和 $变量名$
    result = template
    for var in TEMPLATE_VARIABLES.keys():
        # var 是 "{工作流名称}" 格式，需要提取 "工作流名称"
        var_name = var[1:-1]  # 去掉花括号
        value = mapping.get(var_name, "")
        # 替换 {变量名} 格式
        result = result.replace(var, value)
        # 同时替换 $变量名$ 格式（如果用户使用了这种格式）
        result = result.replace(f"${var_name}$", value)
    
    return result


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

    if requests is None:
        return False, "requests 库未安装，请执行: pip install requests"
    
    # L5 修复：避免双重前缀
    # 旧实现 `if keyword and keyword not in message` 在用户模板已写 "【关键字】..." 时也只检测裸关键字，
    # 不会发现已加的前缀，结果会再加一遍。改为正则匹配 "【关键字】" 在消息开头是否已存在。
    if keyword:
        import re
        prefix_pattern = re.compile(r"^\s*【" + re.escape(keyword) + r"】")
        if not prefix_pattern.search(message) and keyword not in message:
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
