"""运行耗时显示工具。"""

from __future__ import annotations

from typing import Optional


def format_duration_short(duration_seconds: Optional[float]) -> str:
    """格式化为紧凑耗时文案。"""
    if duration_seconds is None:
        return ""

    ds = max(0.0, float(duration_seconds))
    if ds < 60:
        return f"{ds:.0f}s"
    if ds < 3600:
        minutes = int(ds // 60)
        seconds = int(ds % 60)
        return f"{minutes}m{seconds:02d}s"

    hours = int(ds // 3600)
    minutes = int((ds % 3600) // 60)
    return f"{hours}h{minutes:02d}m"
