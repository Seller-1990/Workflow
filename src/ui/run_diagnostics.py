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
    manual_required = int(bucket.get("manual_required", 0) or 0)
    background_risk = int(bucket.get("background_risk", 0) or 0)
    orphan_risk = int(bucket.get("orphan_risk", 0) or 0)
    risk_parts = []
    if manual_required:
        risk_parts.append(f"{manual_required} 个步骤需要人工确认")
    if background_risk:
        risk_parts.append(f"{background_risk} 个步骤可能仍有后台任务")
    if orphan_risk:
        risk_parts.append(f"{orphan_risk} 个子工作流可能仍在后台运行")
    risk_note = "；".join(risk_parts)

    if status_value == "cancelled":
        if running or pending:
            return f"停止请求已送达，仍有 {running + pending} 个步骤等待取消收尾"
        if cancelled:
            return f"已取消，{cancelled} 个未完成步骤已标记为取消"
        return "已取消，未发现残留运行步骤"
    if status_value == "failure":
        if risk_note:
            return f"运行失败，{risk_note}"
        return f"运行失败，{failures} 个步骤失败" if failures else "运行失败，未找到失败步骤摘要"
    if status_value == "running":
        return "运行中，正在等待步骤状态回写"
    if status_value == "success":
        return "运行成功，所有必要步骤已完成"
    return "等待运行开始"
