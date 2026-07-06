# -*- coding: utf-8 -*-
"""主窗口运行态 UI 计算逻辑。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunLockState:
    clear_stale_running: bool
    lock_panels: bool
    show_background_label: bool
    background_label_text: str = ""


def compute_header_run_state(*, engine_running: bool, stopping: bool = False) -> str:
    """计算顶部主按钮状态。"""
    if stopping:
        return "stopping"
    if engine_running:
        return "running"
    return "idle"


def compute_run_lock_state(
    *,
    running_id: int | None,
    current_id: int | None,
    engine_running: bool,
    stopping: bool = False,
    running_name: str | None = None,
) -> RunLockState:
    """计算主窗口在运行态下的面板锁定和后台运行提示。"""
    if running_id is not None and not engine_running:
        return RunLockState(
            clear_stale_running=True,
            lock_panels=False,
            show_background_label=False,
        )

    lock_panels = running_id is not None and running_id == current_id
    show_background_label = running_id is not None and running_id != current_id and not stopping
    label_text = ""
    if show_background_label:
        label_text = f"↻ 后台运行：{running_name or f'#{running_id}'}"

    return RunLockState(
        clear_stale_running=False,
        lock_panels=lock_panels,
        show_background_label=show_background_label,
        background_label_text=label_text,
    )
