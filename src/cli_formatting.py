# -*- coding: utf-8 -*-
"""Pure CLI formatting helpers."""

from duration_utils import format_duration_short


def format_step_finished_line(step_name: str, status: str, duration_seconds=None) -> str:
    duration_text = format_duration_short(duration_seconds)
    suffix = f" · 耗时 {duration_text}" if duration_text else ""
    if status == "success":
        return f"  OK [{step_name}] 完成{suffix}"
    if status == "cancelled":
        return f"  CANCEL [{step_name}] 已取消{suffix}"
    if status == "skipped":
        return f"  SKIP [{step_name}] 已跳过{suffix}"
    return f"  FAIL [{step_name}] 状态: {status}{suffix}"
