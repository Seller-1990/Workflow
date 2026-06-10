# -*- coding: utf-8 -*-
"""Power BI Service REST 刷新客户端（M5 无人值守方案）

Power BI Desktop 桌面刷新需要人工完成"刷新确认、保存并关闭"，无人值守场景必然超时。
本模块通过 Power BI Service REST API 触发数据集刷新并轮询结果：

- POST /groups/{workspace_id}/datasets/{dataset_id}/refreshes 触发刷新（期望 202）
- GET  同地址 ?$top=1 轮询最近一次刷新状态，直至 Completed / Failed / 超时

所有失败以 PowerBIRestError 抛出，message 为可直接展示给用户的中文说明；
任何日志与错误信息都不得包含 access token。
"""

import time

import requests

# Power BI Service REST API 基地址（myorg = 调用者所在组织）
POWERBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"

# 单次 HTTP 请求超时（秒），与整体轮询上限 timeout_seconds 相互独立
REQUEST_TIMEOUT = 30

# 错误信息中响应正文摘录的最大长度（字符）
BODY_EXCERPT_LIMIT = 200

# 鉴权失败的统一提示（触发与轮询阶段共用）
_TOKEN_ERROR_MESSAGE = "访问令牌无效或权限不足（需要数据集读写权限与工作区访问）"


class PowerBIRestError(Exception):
    """REST 刷新失败；message 为面向用户的中文说明，不包含 token"""


def _excerpt(text, limit: int = BODY_EXCERPT_LIMIT) -> str:
    """压缩空白并截取响应正文摘录，避免错误信息过长"""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "..."


def _raise_for_trigger_response(response) -> None:
    """校验触发刷新的响应；非 202 时抛出带中文说明的 PowerBIRestError"""
    status_code = getattr(response, "status_code", None)
    if status_code == 202:
        return
    body = getattr(response, "text", "") or ""
    lowered = body.lower()
    if status_code == 400 and ("another refresh" in lowered or "in progress" in lowered):
        raise PowerBIRestError("已有刷新正在进行中，请稍后再试")
    if status_code in (401, 403):
        raise PowerBIRestError(_TOKEN_ERROR_MESSAGE)
    if status_code == 404:
        raise PowerBIRestError("工作区或数据集不存在，请检查 --workspace-id / --dataset-id 是否正确")
    raise PowerBIRestError(f"触发刷新失败 (HTTP {status_code}): {_excerpt(body)}")


def _evaluate_poll_response(response, log) -> str:
    """解析轮询响应，返回最近一次刷新的 status

    - Failed / Disabled / 鉴权失败：直接抛出 PowerBIRestError
    - 其它非 200 响应、响应体异常：按瞬时故障处理（记日志后继续轮询），
      由整体 deadline 兜底，避免长刷新被单次服务端抖动打断
    """
    status_code = getattr(response, "status_code", None)
    if status_code in (401, 403):
        raise PowerBIRestError(_TOKEN_ERROR_MESSAGE)
    if status_code != 200:
        log(f"查询刷新状态返回 HTTP {status_code}，将在下个轮询周期重试")
        return ""

    try:
        payload = response.json()
    except ValueError:
        log("刷新状态响应不是有效 JSON，将在下个轮询周期重试")
        return ""

    entries = payload.get("value") if isinstance(payload, dict) else None
    if not entries:
        log("刷新记录尚未可见，继续等待...")
        return ""

    latest = entries[0] if isinstance(entries[0], dict) else {}
    status = str(latest.get("status") or "")
    if status == "Failed":
        detail = _excerpt(latest.get("serviceExceptionJson") or "")
        raise PowerBIRestError(f"REST 刷新失败: {detail or '服务未返回失败详情'}")
    if status == "Disabled":
        raise PowerBIRestError("数据集刷新被禁用，请在 Power BI Service 中启用该数据集的计划刷新能力")
    if status != "Completed":
        log(f"刷新进行中，当前状态: {status or 'Unknown'}")
    return status


def refresh_dataset(
    workspace_id: str,
    dataset_id: str,
    access_token: str,
    *,
    timeout_seconds: int,
    poll_interval: float,
    http=None,
    sleep=time.sleep,
    monotonic=time.monotonic,
    should_cancel=None,
    log_cb=None,
) -> None:
    """触发数据集刷新并轮询直至完成

    Args:
        workspace_id: 工作区 GUID
        dataset_id: 数据集 GUID
        access_token: Power BI REST API 访问令牌（绝不写入日志或错误信息）
        timeout_seconds: 整体轮询上限（秒）
        poll_interval: 轮询间隔（秒）
        http: HTTP 客户端，默认 requests 模块（测试可注入脚本化假对象）
        sleep: 等待函数，默认 time.sleep（测试可注入假时钟）
        monotonic: 单调时钟，默认 time.monotonic（测试可注入假时钟）
        should_cancel: 可选回调，返回 True 时中止并抛出"用户取消"
        log_cb: 可选回调，接收中文进度日志行

    Raises:
        PowerBIRestError: 触发失败、刷新失败、刷新被禁用、用户取消或轮询超时
    """
    if http is None:
        http = requests

    def _log(message: str) -> None:
        if log_cb is not None:
            log_cb(message)

    headers = {"Authorization": f"Bearer {access_token}"}
    refreshes_url = f"{POWERBI_API_BASE}/groups/{workspace_id}/datasets/{dataset_id}/refreshes"

    _log(f"通过 REST API 触发数据集刷新: workspace={workspace_id}, dataset={dataset_id}")
    try:
        response = http.post(
            refreshes_url,
            headers=headers,
            json={"notifyOption": "NoNotification"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise PowerBIRestError(f"网络请求失败（触发刷新）: {exc}") from exc
    _raise_for_trigger_response(response)
    _log(f"刷新请求已受理 (HTTP 202)，开始轮询刷新状态（间隔 {poll_interval}秒，上限 {timeout_seconds}秒）...")

    poll_url = f"{refreshes_url}?$top=1"
    deadline = monotonic() + timeout_seconds
    while True:
        if should_cancel is not None and should_cancel():
            raise PowerBIRestError("用户取消")
        if monotonic() >= deadline:
            raise PowerBIRestError(f"REST 刷新轮询超时 ({timeout_seconds}秒)")

        try:
            poll_response = http.get(poll_url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            raise PowerBIRestError(f"网络请求失败（查询刷新状态）: {exc}") from exc

        if _evaluate_poll_response(poll_response, _log) == "Completed":
            _log("数据集刷新完成 (Completed)")
            return
        sleep(poll_interval)
