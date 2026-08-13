# -*- coding: utf-8 -*-
"""钉钉消息通知模块"""

import logging

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None
import time
from typing import Callable, Optional
from datetime import datetime

from tls_ca import resolve_ca_bundle
from webhook_url_policy import is_valid_dingtalk_webhook_url, mask_webhook_url_for_log


# 瞬时失败重试前的等待秒数（测试可 monkeypatch 为 0）
NOTIFY_TRANSIENT_RETRY_DELAY_SECONDS = 2

# 通知消息模板的默认值。
# L2: 这里是默认模板的唯一权威定义，engine_core/notification.py 与 cli.py
# 的通知装配共用同一字符串，避免两处手写常量产生漂移。
DEFAULT_NOTIFY_MESSAGE_TEMPLATE = "{工作流名称} - {状态} - 编号={运行编号}"


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


def _response_excerpt(text: str, limit: int = 200) -> str:
    """生成可记录的短响应摘要，避免日志塞入整段 HTML。"""
    compact = " ".join(str(text or "").split())
    compact = _redact_access_tokens(compact)
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _redact_access_tokens(text: object) -> str:
    """Redact DingTalk access_token values from provider/errors before returning them to UI/logs."""
    import re

    raw = str(text or "")
    return re.sub(r"(?i)(access_token=)([^\s&#?]+)", r"\1<redacted>", raw)


def _is_ca_bundle_error(error: Exception) -> bool:
    text = str(error)
    return (
        "TLS CA certificate bundle" in text
        or ("certifi" in text and "cacert.pem" in text)
    )


def _format_ca_bundle_error(error: Exception) -> str:
    return (
        "TLS CA 证书文件缺失或路径无效，"
        f"请检查 PyInstaller 是否已打包 certifi/cacert.pem: {_redact_access_tokens(error)}"
    )


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

    if not is_valid_dingtalk_webhook_url(webhook_url):
        safe_url = mask_webhook_url_for_log(webhook_url)
        return False, f"Webhook URL 非法或不受信任: {safe_url}"

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
            verify=str(resolve_ca_bundle()),
            headers={"Content-Type": "application/json"}
        )

        status_code = getattr(response, "status_code", None)
        try:
            result = response.json()
        except ValueError:
            excerpt = _response_excerpt(getattr(response, "text", ""))
            status = f"HTTP {status_code}" if status_code is not None else "HTTP 状态未知"
            return False, f"发送失败: {status}, 响应不是 JSON: {excerpt or '空响应'}"

        if status_code is not None and status_code >= 400:
            excerpt = _response_excerpt(getattr(response, "text", ""))
            message_text = _redact_access_tokens(result.get("errmsg") or excerpt or "未知错误")
            return False, f"发送失败: HTTP {status_code}: {message_text}"
        
        if result.get("errcode") == 0:
            return True, "发送成功"
        else:
            message_text = _redact_access_tokens(result.get("errmsg", "未知错误"))
            return False, f"发送失败: {message_text}"
    
    except requests.exceptions.Timeout:
        return False, "请求超时"
    except requests.exceptions.RequestException as e:
        if _is_ca_bundle_error(e):
            return False, _format_ca_bundle_error(e)
        return False, f"请求错误: {_redact_access_tokens(e)}"
    except Exception as e:
        if _is_ca_bundle_error(e):
            return False, _format_ca_bundle_error(e)
        logger.exception("钉钉通知发送异常（非网络错误）: %s", type(e).__name__)
        return False, f"未知错误: {_redact_access_tokens(e)}"


def _is_transient_send_failure(message: str) -> bool:
    """判断失败是否为瞬时故障（超时 / 网络错误 / HTTP 5xx），可安全重试。"""
    text = str(message or "")
    return (
        text.startswith("请求超时")
        or text.startswith("请求错误")
        or "HTTP 5" in text
    )


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
    
    ok, msg = send_dingtalk_message(webhook_url, message, keyword)
    # 瞬时失败（超时 / 网络错误 / HTTP 5xx）等待后重试一次；
    # URL 非法、errcode 业务错误、HTTP 4xx 等非瞬时失败立即返回。
    if not ok and _is_transient_send_failure(msg):
        time.sleep(NOTIFY_TRANSIENT_RETRY_DELAY_SECONDS)
        ok, msg = send_dingtalk_message(webhook_url, message, keyword)
    return ok, msg


def resolve_workflow_notification_target(
    workflow,
    get_webhook_by_id: Callable[[int], object],
) -> Optional[tuple[object, str]]:
    """解析工作流的通知发送目标（规范实现 / canonical resolver）。

    封装「读取 notify 配置 → enabled 检查 → webhook_id 检查 → webhook 查询 →
    模板提取（含默认模板）」这段在 cli.py 与 engine_core/notification.py 中
    重复出现的流程；engine_core 后续可直接改用本函数。

    Args:
        workflow: 提供 ``get_notify_config()`` 的工作流对象
        get_webhook_by_id: webhook 查询函数（注入依赖，避免 notifier 反向依赖 database）

    Returns:
        (webhook, template) 元组；未启用通知 / 未绑定 webhook_id /
        机器人配置缺失时返回 None。
    """
    notify_config = workflow.get_notify_config()
    if not isinstance(notify_config, dict) or not notify_config.get("enabled"):
        return None

    webhook_id = notify_config.get("webhook_id")
    if not webhook_id:
        return None

    webhook = get_webhook_by_id(webhook_id)
    if not webhook:
        return None

    template = notify_config.get("message_template", DEFAULT_NOTIFY_MESSAGE_TEMPLATE)
    return webhook, template


def get_template_variables_help() -> str:
    """获取模板变量帮助文本"""
    return "可用变量：{工作流名称} {状态} {运行编号} {日志目录} {原因} {开始时间} {耗时} {失败摘要}"
