# -*- coding: utf-8 -*-
"""Pure helpers for run-history diagnostic text."""


def build_run_diagnostic(status: str, counts: dict[str, int] | None) -> str:
    """Return a short user-facing diagnostic for a run-history row."""
    status_value = status or "pending"
    bucket = counts or {}
    failures = int(bucket.get("failure", 0) or 0)
    cancelled = int(bucket.get("cancelled", 0) or 0)
    running = int(bucket.get("running", 0) or 0)
    pending = int(bucket.get("pending", 0) or 0)

    if status_value == "cancelled":
        if running or pending:
            return f"停止请求已送达，仍有 {running + pending} 个步骤等待取消收尾"
        if cancelled:
            return f"已取消，{cancelled} 个未完成步骤已标记为取消"
        return "已取消，未发现残留运行步骤"
    if status_value == "failure":
        return f"运行失败，{failures} 个步骤失败" if failures else "运行失败，未找到失败步骤摘要"
    if status_value == "running":
        return "运行中，正在等待步骤状态回写"
    if status_value == "success":
        return "运行成功，所有必要步骤已完成"
    return "等待运行开始"
